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
    "idle_has_no_timer", "fox_icon_shown", "native_exit_removed_icon_and_timer", "window_closed",
    "visible_ui_healthy",
    "unregistered_tray_cannot_hide",
    "hidden_and_minimized_panel_motion_stops",
}
EXTENDED_CHECKS = {
    "actual_local_reading_state", "reading_animation_bounded", "reduced_motion_stops_native_timer",
    "cancel_keeps_actual_native_read_truthful", "discard_blocks_new_reads", "discarded_result_stays_hidden",
    "error_state_static_and_generic",
}
# The window's X keeps an active collection beside the clock instead of quitting.
CLOSE_CHECKS = {"active_collection_close_hides"}

def wait(predicate, timeout=15):
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate(): return
        time.sleep(.05)
    smoke.fail("tray_state_timeout")

def inspect(tray):
    data={}
    def read():
        from System.Reflection import BindingFlags
        flags = BindingFlags.Instance | BindingFlags.NonPublic
        field = tray._notify.GetType().GetField("added", flags) or tray._notify.GetType().GetField("iconAdded", flags)
        if field is None: smoke.fail("notify_icon_registration_field_missing")
        data.update(registered=bool(field.GetValue(tray._notify)), visible=bool(tray._notify.Visible),
                    window_visible=bool(tray._form.Visible), activity=tray._current_activity,
                    timer=bool(tray._timer.Enabled), icon=tray._last_icon,
                    frame_updates=tray._frame_updates, tooltip=str(tray._notify.Text),
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
    real_demo=None
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
        wait(lambda:inspect(tray)["activity"]=="idle" and not inspect(tray)["timer"])
        require("idle_has_no_timer")
        require("fox_icon_shown",data["icon"]=="fox-idle")
        for _ in range(6):
            menu(tray._hide_item); require("same_window_after_repeated_show_hide",not inspect(tray)["window_visible"])
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
            media(window,tray,False)
            from coletor.service import PreviewApi
            real_demo=PreviewApi.load_demo
            def held(api):
                if not gate.wait(25): smoke.fail("synthetic_read_gate_timeout")
                return real_demo(api)
            PreviewApi.load_demo=held
            settings.click(window,"Usar dados de exemplo")
            wait(lambda:inspect(tray)["activity"]=="reading" and inspect(tray)["timer"])
            require("actual_local_reading_state","Lendo arquivo local" in inspect(tray)["tooltip"])
            before=inspect(tray)["frame_updates"]; time.sleep(1.95); after=inspect(tray)["frame_updates"]
            require("reading_animation_bounded",2<=after-before<=4)
            result["reading_screenshot"]=smoke.capture_window(handle,args.output_dir/"tray-local-reading.png")
            media(window,tray,True)
            wait(lambda:not inspect(tray)["timer"])
            before=inspect(tray)["frame_updates"];time.sleep(.8)
            require("reduced_motion_stops_native_timer",inspect(tray)["frame_updates"]==before)
            media(window,tray,False)
            settings.click(window,"Descartar resultado")
            smoke.wait_js(window,"document.body.innerText.includes('Lendo o diário')")
            require("cancel_keeps_actual_native_read_truthful",inspect(tray)["activity"]=="reading")
            require("discard_blocks_new_reads", window.evaluate_js("[...document.querySelectorAll('button')].filter(n=>['Usar dados de exemplo','Abrir diário'].includes(n.textContent.trim())).every(n=>n.disabled) && document.querySelector('input[inputmode=numeric]')?.disabled===true"))
            gate.set()
            wait(lambda:inspect(tray)["activity"]=="idle" and not inspect(tray)["timer"])
            # Native end_read occurs before the bridge promise reaches React.
            # Wait for both layers; do not race the legitimately disabled input.
            smoke.wait_js(window, "document.querySelector('input[inputmode=numeric]')?.disabled===false && !document.body.innerText.includes('Lendo o diário')")
            require("discarded_result_stays_hidden", window.evaluate_js("![...document.querySelectorAll('h2')].some(n=>n.textContent==='Prévia da turma')"))
            # A real invalid year reaches the existing local preview validator.
            settings.set_input(window,"Ano","0000")
            expression="""(() => {const input=document.querySelector('input[type=file]');const d=new DataTransfer();d.items.add(new File(['<html>synthetic-invalid</html>'],'synthetic-invalid.html',{type:'text/html'}));input.files=d.files;input.dispatchEvent(new Event('change',{bubbles:true}));return true;})()"""
            window.evaluate_js(expression)
            smoke.wait_js(window,"!!document.querySelector('[role=alert]')")
            wait(lambda:inspect(tray)["activity"]=="error")
            data=inspect(tray)
            require("error_state_static_and_generic",not data["timer"] and data["icon"]=="fox-error" and data["tooltip"].endswith("Arquivo precisa de atenção") and "Coleta desligada" in data["tooltip"])
            result["error_screenshot"]=smoke.capture_window(handle,args.output_dir/"tray-local-error.png")
        require("visible_ui_healthy",window.evaluate_js("document.querySelector('h1')?.textContent==='Coleta da frequência' && document.title.includes('Coletor') && !document.querySelector('vite-error-overlay') && window.__trayQaErrors===0"))
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
        result["status"]="passed"
    except Exception as error:
        result["status"]="failed"
        result["failure"]=str(error) if isinstance(error,(smoke.SmokeFailure, settings.smoke.SmokeFailure)) else "native_tray_flow_failed"
        result["error_type"]=type(error).__name__
    finally:
        gate.set()
        if real_demo is not None:
            from coletor.service import PreviewApi
            PreviewApi.load_demo=real_demo
        smoke.write_json(args.worker_output,result)
        if not tray._disposed:
            if args.scenario=="quit": menu(tray._quit_item)
            else: tray._invoke(tray._form.Close)  # Same WinForms FormClosing path as X.
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
            data=json.loads((isolated/"settings.json").read_text(encoding="utf-8"))
            if set(data)!={"schemaVersion","schedule","theme","fox"}: smoke.fail("unexpected_persistent_data")
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
