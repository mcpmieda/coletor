"""Real WinForms notification-area flows, synthetic reads, isolated preferences."""
import argparse
import faulthandler
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

def module(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result
smoke = module("tray_portable_smoke", "check_windows_portable.py")
settings = module("tray_settings_helpers", "check_windows_settings.py")
SCENARIOS = ("quit", "close")
REQUIRED_CHECKS = {
    "native_window_visible", "native_tray_registered", "native_menu_visible",
    "same_window_after_repeated_show_hide", "left_click_and_double_click_restore_same_window",
    "idle_motion_gentle", "window_icon_follows_fox", "fox_icon_shown", "native_exit_removed_icon_and_timer", "window_closed",
    "visible_ui_healthy",
    "unregistered_tray_cannot_hide",
    "hidden_and_minimized_panel_motion_stops",
}
EXTENDED_CHECKS = {
    "menu_header_shows_live_status", "menu_collect_and_pause_reach_collector", "actual_collection_state",
    "collect_disabled_while_collecting", "reading_animation_bounded", "reduced_motion_stops_native_timer",
    "error_state_static_and_generic", "menu_header_flags_error", "menu_notifications_and_logs",
}
# The window's X keeps an active collection beside the clock instead of quitting.
CLOSE_CHECKS = {"active_collection_close_hides", "inactive_close_hides", "unknown_status_close_hides", "hidden_native_motion_continues"}

def wait(predicate, timeout=15):
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate(): return
        time.sleep(.05)
    smoke.fail("tray_state_timeout")

def inspect(tray):
    data={}
    def read():
        import System
        from System.Reflection import BindingFlags
        flags = BindingFlags.Instance | BindingFlags.NonPublic
        field = tray._notify.GetType().GetField("added", flags) or tray._notify.GetType().GetField("iconAdded", flags)
        if field is None: smoke.fail("notify_icon_registration_field_missing")
        data.update(registered=bool(field.GetValue(tray._notify)), visible=bool(tray._notify.Visible),
                    window_visible=bool(tray._form.Visible), activity=tray._current_activity,
                    timer=bool(tray._timer.Enabled), icon=tray._last_icon,
                    frame_updates=tray._frame_updates, tooltip=str(tray._notify.Text),
                    window_icon_matches=tray._window_icon in tray._icons and System.Object.ReferenceEquals(tray._form.Icon, tray._icons[tray._window_icon])
                        and tray._window_icon == (tray._last_icon if tray._last_icon in tray._icons else "fox-idle"),
                    handle=int(tray._form.Handle.ToInt64()))
    tray._invoke(read)
    return data

def media(window, tray, reduced):
    tasks=[]
    def change():
        pending=list(window.native.Controls)
        while pending:
            control=pending.pop()
            if str(control.GetType().FullName)=="Microsoft.Web.WebView2.WinForms.WebView2":
                tasks.append(control.CoreWebView2.CallDevToolsProtocolMethodAsync("Emulation.setEmulatedMedia",
                    json.dumps({"features":[{"name":"prefers-reduced-motion","value":"reduce" if reduced else "no-preference"}]})))
            pending.extend(list(control.Controls))
    tray._invoke(change)
    if len(tasks)!=1: smoke.fail("native_media_control_missing")
    tasks[0].GetAwaiter().GetResult()
    smoke.wait_js(window,"matchMedia('(prefers-reduced-motion: reduce)').matches==="+str(reduced).lower())
    wait(lambda:tray._state.snapshot()["reduced_motion"] is reduced)

def exercise(window,args,result):
    from System import Array, Object
    from System.Drawing import Point
    from System.Reflection import BindingFlags
    from System.Windows.Forms import MouseEventArgs, MouseButtons, Application, FormWindowState
    checks=result["checks"]
    gate=threading.Event()
    tray=window._coletor_tray
    def require(name, condition=True):
        if not condition: smoke.fail(name)
        checks[name]=True
        result["stage"]=name
        smoke.write_json(args.worker_output,result)
    def menu(item):
        tray._invoke(lambda:item.PerformClick())
    try:
        if tray._disposed: smoke.fail("tray_start_failed_"+getattr(tray,"_startup_error_type","unknown"))
        smoke.wait_js(window,"!!document.querySelector('h1') && !!window.pywebview?.api?.get_desktop_status")
        smoke.wait_js(window,"document.body.innerText.includes('Ocultar na bandeja')")
        window.evaluate_js("window.__trayQaErrors=0;addEventListener('error',()=>window.__trayQaErrors++);addEventListener('unhandledrejection',()=>window.__trayQaErrors++);true")
        info,handle=smoke.native_info(window)
        require("native_window_visible",info["visible"] and info["edgechromium"])
        data=inspect(tray)
        require("native_tray_registered",data["registered"] and data["visible"])
        tray._invoke(lambda:setattr(tray._notify,"Visible",False))
        require("unregistered_tray_cannot_hide","error" in tray.hide() and inspect(tray)["window_visible"] and not tray.available())
        tray._invoke(lambda:setattr(tray._notify,"Visible",True))
        wait(lambda:inspect(tray)["registered"])
        # Resting fox: a gesture every few seconds (blinks, ear wags), at most
        # 14 frame changes in any 13 s window.
        # CI images often disable Windows animations (prefers-reduced-motion),
        # which correctly keeps the fox still; measure motion with it allowed.
        media(window,tray,False)
        wait(lambda:inspect(tray)["activity"]=="idle" and inspect(tray)["timer"])
        before=inspect(tray)["frame_updates"]; time.sleep(13); after=inspect(tray)
        result["idle_frame_updates"]=after["frame_updates"]-before
        require("idle_motion_gentle",8<=after["frame_updates"]-before<=22)
        require("window_icon_follows_fox",after["window_icon_matches"])
        require("fox_icon_shown",data["icon"] in {"fox-idle","fox-blink","fox-ear"})
        for _ in range(6):
            tray._invoke(tray._hide); require("same_window_after_repeated_show_hide",not inspect(tray)["window_visible"])
            menu(tray._open_item); menu(tray._open_item)
            require("same_window_after_repeated_show_hide",inspect(tray)["window_visible"] and inspect(tray)["handle"]==handle)
        settings.click(window,"Ocultar na bandeja")
        wait(lambda:not inspect(tray)["window_visible"])
        result["hidden_document"] = bool(window.evaluate_js("document.hidden"))
        result["hidden_panel_motion"] = window.evaluate_js("document.querySelector('.fox-stage')?.dataset.motion ?? 'absent'")
        smoke.wait_js(window,"window.__coletorWindowVisible===false && (!document.querySelector('.fox-stage') || document.querySelector('.fox-stage').dataset.motion==='off')")
        def mouse_restore():
            flags=BindingFlags.Instance|BindingFlags.NonPublic
            for method,clicks in (("OnMouseClick",1),("OnMouseDoubleClick",2),("OnMouseDoubleClick",2)):
                tray._notify.GetType().GetMethod(method,flags).Invoke(tray._notify,
                    Array[Object]([MouseEventArgs(MouseButtons.Left,clicks,0,0,0)]))
            if Application.OpenForms.Count != 1: smoke.fail("duplicate_native_window")
        tray._invoke(mouse_restore)
        require("left_click_and_double_click_restore_same_window",inspect(tray)["window_visible"] and inspect(tray)["handle"]==handle)
        tray._invoke(lambda:setattr(window.native,"WindowState",FormWindowState.Minimized))
        smoke.wait_js(window,"window.__coletorWindowVisible===false && (!document.querySelector('.fox-stage') || document.querySelector('.fox-stage').dataset.motion==='off')")
        menu(tray._open_item)
        smoke.wait_js(window,"window.__coletorWindowVisible===true")
        require("hidden_and_minimized_panel_motion_stops")
        tray._invoke(lambda:tray._menu.Show(Point(window.native.Left+340,window.native.Top+250)))
        wait(lambda:bool(tray._menu.Visible))
        require("native_menu_visible")
        result["menu_screenshot"]=smoke.capture_window(int(tray._menu.Handle.ToInt64()),args.output_dir/("tray-menu-"+args.scenario+".png"))
        tray._invoke(tray._menu.Close)
        if args.scenario=="quit":
            # Unattended collection drives the fox: simulate the collector's
            # states through the same provider the desktop bridge installs.
            real_status=tray.status_provider
            calls=[]
            tray.collect_action=lambda:calls.append("collect")
            tray.pause_action=lambda paused:calls.append(("pause",paused))
            try:
                tray.status_provider=lambda:{"active":True,"state":"ready","localPaused":False}
                tray._invoke(lambda:tray._menu_opening())
                require("menu_header_shows_live_status","\nColeta ativa" in tray._status_item.Text and tray._collect_item.Enabled)
                menu(tray._collect_item); menu(tray._pause_item)
                wait(lambda:calls==["collect",("pause",True)])
                require("menu_collect_and_pause_reach_collector")
                tray.notifications_provider=lambda:True
                tray.notifications_action=lambda show:calls.append(("notifications",show))
                tray.logs_action=lambda:calls.append("logs")
                tray._invoke(lambda:tray._menu_opening())
                checked_before=bool(tray._notify_item.Checked)
                menu(tray._notify_item); menu(tray._logs_item)
                wait(lambda:("notifications",False) in calls and "logs" in calls)
                require("menu_notifications_and_logs",checked_before and not tray._notify_item.Checked
                        # Same composition as the Atualizador: header, then these items in order.
                        and [i.Text for i in tray._menu.Items if i.Text][1:]==["Abrir painel","Coletar agora","Pausar a coleta",
                            "Mostrar notificações","Abrir pasta de logs","Encerrar coletor"])
                media(window,tray,False)
                tray.status_provider=lambda:{"active":True,"state":"collecting","localPaused":False}
                tray._invoke(tray._refresh)
                wait(lambda:inspect(tray)["activity"]=="reading" and inspect(tray)["timer"])
                require("actual_collection_state","Coletando" in inspect(tray)["tooltip"])
                tray._invoke(lambda:tray._menu_opening())
                require("collect_disabled_while_collecting",not tray._collect_item.Enabled)
                before=inspect(tray)["frame_updates"]; time.sleep(1.95); after=inspect(tray)["frame_updates"]
                result["reading_frame_updates"]=after-before
                require("reading_animation_bounded",2<=after-before<=4)
                result["reading_screenshot"]=smoke.capture_window(handle,args.output_dir/"tray-collecting.png")
                media(window,tray,True)
                wait(lambda:not inspect(tray)["timer"])
                before=inspect(tray)["frame_updates"];time.sleep(.8)
                require("reduced_motion_stops_native_timer",inspect(tray)["frame_updates"]==before)
                media(window,tray,False)
                tray.status_provider=lambda:{"active":True,"state":"error","localPaused":False}
                tray._invoke(tray._refresh)
                wait(lambda:inspect(tray)["activity"]=="error")
                data=inspect(tray)
                require("error_state_static_and_generic",not data["timer"] and data["icon"]=="fox-error" and data["tooltip"].endswith("Precisa de atenção"))
                tray._invoke(lambda:tray._menu_opening())
                require("menu_header_flags_error",tray._status_item.Text.split("\n")[1].startswith("!"))
                result["error_screenshot"]=smoke.capture_window(handle,args.output_dir/"tray-error.png")
            finally:
                tray.status_provider=real_status
                tray._invoke(tray._refresh)
        require("visible_ui_healthy",window.evaluate_js("document.querySelector('h1')?.textContent==='Tarefas' && document.title.includes('Coletor') && !document.querySelector('vite-error-overlay') && window.__trayQaErrors===0"))
        if args.scenario=="close":
            real_status=tray.status_provider
            tray.status_provider=lambda:{"active":True,"state":"ready"}
            try:
                tray._invoke(tray._form.Close)
                wait(lambda:not inspect(tray)["window_visible"])
                require("active_collection_close_hides",not tray._disposed and not window.native.IsDisposed)
            finally:
                tray.status_provider=real_status
            menu(tray._open_item)
            wait(lambda:inspect(tray)["window_visible"])
            for status, check in (({'active': False, 'state': 'connect'}, 'inactive_close_hides'), (None, 'unknown_status_close_hides')):
                tray.status_provider=lambda value=status: value
                tray._invoke(tray._refresh)
                tray._invoke(tray._form.Close)
                wait(lambda:not inspect(tray)["window_visible"])
                require(check, not tray._disposed and not window.native.IsDisposed)
                before=inspect(tray)["frame_updates"]
                time.sleep(3.1)
                after=inspect(tray)
                require("hidden_native_motion_continues", after["registered"] and after["timer"] and after["frame_updates"] > before)
                menu(tray._open_item)
                wait(lambda:inspect(tray)["window_visible"])
                require("same_window_after_repeated_show_hide",inspect(tray)["handle"]==handle)
            tray.status_provider=real_status
        result["status"]="passed"
    except Exception as error:
        result["status"]="failed"
        result["failure"]=str(error) if isinstance(error,(smoke.SmokeFailure, settings.smoke.SmokeFailure)) else "native_tray_flow_failed"
        result["error_type"]=type(error).__name__
    finally:
        gate.set()
        smoke.write_json(args.worker_output,result)
        if not tray._disposed:
            if args.scenario=="quit": menu(tray._quit_item)
            else: menu(tray._quit_item)  # Explicit exit, unlike the window's X.
        if not window.native.IsDisposed: window.destroy()

def worker(args):
    if sys.stdin.readline()!="RUN\n": return 2
    result={"status":"failed","scenario":args.scenario,"checks":{}}
    try:
        program=smoke.validate_package(args.package_root)
        import coletor.desktop as desktop
        if not Path(desktop.__file__).resolve().is_relative_to(program): smoke.fail("bundled_tray_application_required")
        holder={}
        def callback(window):
            holder["tray"]=window._coletor_tray
            exercise(window,args,result)
        result["stage"]="launch_native_window"
        smoke.write_json(args.worker_output,result)
        with (args.output_dir/("tray-thread-diagnostic-"+args.scenario+".txt")).open("w",encoding="utf-8") as diagnostic:
            faulthandler.dump_traceback_later(25, file=diagnostic)
            try: desktop.run_desktop(callback=callback,settings_directory=args.settings_directory, access=smoke.synthetic_institutional_access())
            finally: faulthandler.cancel_dump_traceback_later()
        tray=holder.get("tray")
        result["checks"]["native_exit_removed_icon_and_timer"]=bool(tray and tray._disposed and tray._cleanup_ok and not tray._icons and not tray._notify.Visible and not tray._timer.Enabled)
        result["checks"]["window_closed"]=True
        required=REQUIRED_CHECKS | (EXTENDED_CHECKS if args.scenario=="quit" else CLOSE_CHECKS)
        if not all(result["checks"].get(n) is True for n in required): result["status"]="failed"
    except BaseException as error:
        result["status"]="failed";result.setdefault("failure",str(error) if isinstance(error,smoke.SmokeFailure) else "tray_worker_failed")
        result["error_type"]=type(error).__name__
    smoke.write_json(args.worker_output,result)
    # Names/daemon flags only: diagnose a worker that completed GUI checks but
    # cannot exit; never record diary content, stack locals or exceptions.
    result["threads_at_return"]=[{"name":t.name,"daemon":t.daemon} for t in threading.enumerate()]
    smoke.write_json(args.worker_output,result)
    return 0 if result["status"]=="passed" else 1

def orchestrator(args):
    report={"test":"portable_windows_tray","status":"failed","synthetic_data_only":True,"window_test":True,
            "started_at":datetime.now(timezone.utc).isoformat(),"workers":[],"cleanup":{"verified":True,"remaining_processes":0}}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    try:
        if sys.platform!="win32": smoke.fail("windows_runner_required")
        program=smoke.validate_package(args.package_root)
        if not smoke.probe_webview2()["installed"]: smoke.fail("webview2_missing_no_install_attempted")
        with tempfile.TemporaryDirectory(prefix="coletor-tray-test-") as temporary:
            root=Path(temporary); isolated=root/"ColetorFrequenciaSmecel"
            for scenario in SCENARIOS:
                output=root/(scenario+".json");job=smoke.WindowsJob();process=None
                try:
                    command=[str(program/"python.exe"),"-I",str(Path(__file__).resolve()),"--package-root",str(args.package_root),
                             "--output-dir",str(args.output_dir),"--worker","--worker-output",str(output),
                             "--settings-directory",str(isolated),"--scenario",scenario]
                    process=subprocess.Popen(command,cwd=root,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    job.assign(process.pid)
                    timed_out=False
                    try: process.communicate(input=b"RUN\n",timeout=args.timeout)
                    except subprocess.TimeoutExpired: timed_out=True
                    finally:
                        cleanup=job.finish(grace=0 if process.poll() is None else 5);process.wait(timeout=10)
                        report["cleanup"]["verified"] &= cleanup["verified"]
                        report["cleanup"]["remaining_processes"] += cleanup["remaining_processes"]
                    result=json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {"status":"failed"}
                    result["cleanup"]=cleanup;report["workers"].append(result)
                    if timed_out: smoke.fail("tray_native_timeout")
                    if process.returncode!=0 or result["status"]!="passed": smoke.fail("tray_scenario_failed")
                finally:
                    job.close()
                    if process is not None and process.poll() is None: process.kill();process.wait(timeout=10)
            # The tray flows change no preference; a settings file appears only if one is saved.
            settings_file=isolated/"settings.json"
            if settings_file.is_file() and set(json.loads(settings_file.read_text(encoding="utf-8")))!={"schemaVersion","schedule","theme","fox"}:
                smoke.fail("unexpected_persistent_data")
            report["only_nonsecret_settings_retained"]=True
            if report["cleanup"]["verified"]:report["status"]="passed"
    except BaseException as error:
        report["failure"]=str(error) if isinstance(error,smoke.SmokeFailure) else "tray_orchestrator_failed"
        report["error_type"]=type(error).__name__
    smoke.write_json(args.output_dir/"windows-tray-smoke.json",report)
    print(json.dumps({"status":report["status"],"failure":report.get("failure"),"evidence":"windows-tray-smoke.json"}))
    return 0 if report["status"]=="passed" else 1

def parse_args():
    parser=argparse.ArgumentParser(description=__doc__)
    package=parser.add_mutually_exclusive_group(required=True)
    package.add_argument("--package-root",type=Path);package.add_argument("--python",type=Path,dest="python_executable")
    parser.add_argument("--output-dir",type=Path,required=True);parser.add_argument("--timeout",type=float,default=150)
    parser.add_argument("--worker",action="store_true",help=argparse.SUPPRESS)
    parser.add_argument("--worker-output",type=Path,help=argparse.SUPPRESS)
    parser.add_argument("--settings-directory",type=Path,help=argparse.SUPPRESS)
    parser.add_argument("--scenario",choices=SCENARIOS,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if not 10<=args.timeout<=600:parser.error("Invalid timeout")
    if args.worker and not all((args.worker_output,args.settings_directory,args.scenario)):parser.error("Missing internal worker arguments")
    if args.python_executable is not None:
        if args.python_executable.name.lower()!="python.exe":parser.error("Bundled python.exe required")
        args.package_root=args.python_executable.resolve().parent.parent
    args.package_root=args.package_root.resolve();args.output_dir=args.output_dir.resolve()
    return args

if __name__=="__main__":
    args=parse_args()
    raise SystemExit(worker(args) if args.worker else orchestrator(args))
