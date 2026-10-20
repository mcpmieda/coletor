"""Native portable settings close/reopen/recovery test; synthetic settings only."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
spec=importlib.util.spec_from_file_location("portable_smoke",Path(__file__).with_name("check_windows_portable.py"))
smoke=importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
SCENARIOS=("save","reopen","restored","recovered")


def click(window,label,root="document"):
    expression="""(() => {const label=%s; const n=[...%s.querySelectorAll('button')].find(n=>n.textContent.trim()===label || n.getAttribute('aria-label')===label); if(!n||n.disabled)return false;n.click();return true;})()""" % (json.dumps(label),root)
    if not window.evaluate_js(expression): smoke.fail("settings_button_unavailable")


def page(window,label):
    click(window,label,"(document.querySelector('nav[aria-label=\"Navegação principal\"]')||document)")
    smoke.wait_js(window,"[...document.querySelectorAll('h1')].some(n=>n.textContent.trim()===%s)" % json.dumps(label))


def select_saturday_morning(window):
    """Select Saturday/morning without flattening the per-shift shared agenda."""
    smoke.wait_js(window, "!!document.querySelector('[role=dialog] button[aria-haspopup="listbox"], [role=dialog] [role=combobox]')")
    selected = window.evaluate_js("""(() => {
        const trigger=document.querySelector('[role=dialog] button[aria-haspopup="listbox"], [role=dialog] [role=combobox]');
        if (!trigger) return false;
        trigger.click(); return true;
    })()""")
    if not selected: smoke.fail("schedule_day_turn_selector_unavailable")
    smoke.wait_js(window, """[...document.querySelectorAll('[role=option]')].some(
        n=>n.textContent.includes('Sábado') && n.textContent.includes('Matutino'))""")
    selected = window.evaluate_js("""(() => {
        const option=[...document.querySelectorAll('[role=option]')].find(
            n=>n.textContent.includes('Sábado') && n.textContent.includes('Matutino'));
        if (!option) return false;
        option.click(); return true;
    })()""")
    if not selected: smoke.fail("schedule_saturday_morning_option_unavailable")
    smoke.wait_js(window, """document.querySelector('[role=dialog] button[aria-haspopup="listbox"], [role=dialog] [role=combobox]')?.textContent.includes('Sábado')""")


def saturday_js(selected):
    # HeroUI Switch exposes aria-checked or checked, not the old aria-pressed.
    return """(() => {
        const n=document.querySelector('[role=dialog] [role=switch], [role=dialog] input[type=checkbox]');
        return !!n && (n.getAttribute('aria-checked')==='true' || n.checked===true)===%s;
    })()""" % json.dumps(selected)


def toggle_saturday(window, selected):
    pressed = window.evaluate_js("""(() => {
        const n=document.querySelector('[role=dialog] [role=switch], [role=dialog] input[type=checkbox]');
        if (!n || n.disabled) return false;
        n.click(); return true;
    })()""")
    if not pressed: smoke.fail("schedule_saturday_switch_unavailable")
    smoke.wait_js(window,saturday_js(selected))


def open_agenda(window):
    page(window,"Tarefas")
    smoke.wait_js(window,"[...document.querySelectorAll('button')].some(n=>n.getAttribute('aria-label')==='Editar agenda'&&!n.disabled)")
    click(window,"Editar agenda")
    smoke.wait_js(window,"!!document.querySelector('[role=dialog] button[aria-haspopup="listbox"], [role=dialog] [role=combobox]')")
    select_saturday_morning(window)


def save_agenda(window):
    smoke.wait_js(window,"[...document.querySelector('[role=dialog]').querySelectorAll('button')].some(n=>n.textContent.trim()==='Salvar'&&!n.disabled)")
    click(window,"Salvar","document.querySelector('[role=dialog]')")
    smoke.wait_js(window,"!document.querySelector('[role=dialog]')")


def stored(window,predicate):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        window.evaluate_js("window.__localSettingsProbe=null;Promise.all([window.pywebview.api.get_local_settings(),window.pywebview.api.get_collector_status()]).then(([r,c])=>{window.__localSettingsProbe={settings:r.settings,notice:r.notice,shared:c.settings?.schedule||null};});true")
        smoke.wait_js(window,"!!window.__localSettingsProbe",timeout=10)
        result=window.evaluate_js("window.__localSettingsProbe")
        if predicate(result): return result
        time.sleep(.1)
    smoke.fail("settings_disk_acknowledgement_timeout")


def saturday_stored(result):
    """Shared agenda: weekday 6 is Saturday."""
    rules=(result.get("shared") or {}).get("rules") or []
    return any(r["weekday"]==6 and r["enabled"] for r in rules)


def exercise(window,args,result):
    checks=result["checks"]
    def require(name,value=True):
        if not value: smoke.fail(name)
        checks[name]=True
    try:
        smoke.wait_js(window,"!!document.querySelector('nav[aria-label=\"Navegação principal\"]') && typeof window.pywebview?.api?.get_local_settings==='function'")
        info,handle=smoke.native_info(window)
        require("native_window_visible",info["visible"] and info["edgechromium"])
        if args.scenario=="save":
            result["stage"]="open_per_shift_agenda"
            open_agenda(window)
            require("fresh_default_schedule_weekdays_only",window.evaluate_js(saturday_js(False)))
            click(window,"Adicionar horário","document.querySelector('[role=dialog]')")
            smoke.wait_js(window,"!!document.querySelector('[role=dialog] [data-time-row]')")
            result["stage"]="enable_saturday_morning"
            toggle_saturday(window,True)
            result["stage"]="save_shared_agenda"
            save_agenda(window)
            page(window,"Ajustes")
            click(window,"Escuro")
            smoke.wait_js(window,"document.documentElement.dataset.theme==='dark'")
            stored(window,lambda r:saturday_stored(r) and r["settings"]["theme"]=="dark")
            require("agenda_and_theme_saved_to_disk")
        elif args.scenario=="reopen":
            require("theme_survives_normal_close",window.evaluate_js("document.documentElement.dataset.theme==='dark'"))
            require("fox_always_shown",window.evaluate_js("!!document.querySelector('.fox-stage')"))
            open_agenda(window)
            require("agenda_survives_normal_close",window.evaluate_js(saturday_js(True)))
            toggle_saturday(window,False)
            stored(window,saturday_stored)
            require("toggle_does_not_save_implicitly")
            save_agenda(window)
            stored(window,lambda r:not saturday_stored(r))
            require("restored_schedule_saved")
        elif args.scenario=="restored":
            require("other_preferences_preserved",window.evaluate_js("document.documentElement.dataset.theme==='dark' && !!document.querySelector('.fox-stage')"))
            open_agenda(window)
            require("restored_schedule_survives_close",window.evaluate_js(saturday_js(False)))
            click(window,"Cancelar","document.querySelector('[role=dialog]')")
        else:
            require("corrupt_file_defaults_visible",window.evaluate_js("document.documentElement.dataset.theme!=='dark' && !!document.querySelector('.fox-stage')"))
            open_agenda(window)
            require("shared_agenda_unaffected_by_local_file",window.evaluate_js(saturday_js(False)))
            click(window,"Cancelar","document.querySelector('[role=dialog]')")
            page(window,"Ajustes")
            click(window,"Escuro")
            stored(window,lambda r:not r.get("notice") and r["settings"]["theme"]=="dark")
            require("explicit_save_recovers_valid_file")
        window.evaluate_js("window.scrollTo(0,0)")
        result["screenshot"]=smoke.capture_window(handle,args.output_dir/("settings-"+args.scenario+".png"))
        result["status"]="passed"
        result["stage"]="complete"
    except Exception as error:
        result["status"]="failed"
        result.setdefault("stage","other")
        result["failure"]=str(error) if isinstance(error,smoke.SmokeFailure) else "settings_window_check_failed"
        result["error_type"]=type(error).__name__
    finally:
        smoke.write_json(args.worker_output,result)
        smoke.close_window(window)


def worker(args):
    if sys.stdin.readline()!="RUN\n": return 2
    result={"status":"failed","scenario":args.scenario,"checks":{}}
    try:
        program=smoke.validate_package(args.package_root)
        import coletor.desktop as desktop
        if Path(desktop.__file__).resolve().parent.parent.parent!=program: smoke.fail("bundled_settings_application_required")
        desktop.run_desktop(callback=lambda window:exercise(window,args,result),settings_directory=args.settings_directory, access=smoke.synthetic_institutional_access(shared_fixture=args.settings_directory.parent/"shared-school-fixture.json"))
        result["checks"]["window_closed"]=True
    except BaseException as error:
        result["failure"]=str(error) if isinstance(error,smoke.SmokeFailure) else "settings_worker_failed"
        result["error_type"]=type(error).__name__
        result["status"]="failed"
    smoke.write_json(args.worker_output,result)
    return 0 if result["status"]=="passed" else 1


def orchestrator(args):
    report={"test":"portable_windows_local_settings","status":"failed","window_test":True,"synthetic_data_only":True,
            "started_at":datetime.now(timezone.utc).isoformat(),"workers":[],"cleanup":{"verified":True,"remaining_processes":0}}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    try:
        if sys.platform!="win32": smoke.fail("windows_runner_required")
        program=smoke.validate_package(args.package_root)
        if not smoke.probe_webview2()["installed"]: smoke.fail("webview2_prerequisite_missing_no_install_attempted")
        with tempfile.TemporaryDirectory(prefix="coletor-settings-test-") as temporary:
            root=Path(temporary); isolated=root/"ColetorFrequenciaSmecel"
            sentinel=root/"Atualizador de Planilhas"/"settings.json"
            sentinel.parent.mkdir(); sentinel.write_bytes(b"UNRELATED_APP_SENTINEL")
            for scenario in SCENARIOS:
                if scenario=="recovered": (isolated/"settings.json").write_bytes(b"{controlled-invalid-synthetic")
                output=root/(scenario+".json"); job,process=smoke.WindowsJob(),None
                try:
                    command=[str(program/"python.exe"),"-I",str(Path(__file__).resolve()),"--package-root",str(args.package_root),
                             "--output-dir",str(args.output_dir),"--worker","--worker-output",str(output),"--settings-directory",str(isolated),"--scenario",scenario]
                    process=subprocess.Popen(command,cwd=root,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    job.assign(process.pid)
                    try: process.communicate(input=b"RUN\n",timeout=args.timeout)
                    except subprocess.TimeoutExpired: smoke.fail("settings_window_timeout")
                    finally:
                        cleanup=job.finish(grace=0 if process.poll() is None else 5); process.wait(timeout=10)
                        report["cleanup"]["verified"] &= cleanup["verified"]
                        report["cleanup"]["remaining_processes"] += cleanup["remaining_processes"]
                    result=json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {"status":"failed"}
                    result["cleanup"]=cleanup; report["workers"].append(result)
                    if process.returncode!=0 or result["status"]!="passed": smoke.fail("settings_scenario_failed")
                    if sentinel.read_bytes()!=b"UNRELATED_APP_SENTINEL": smoke.fail("other_application_modified")
                    data=json.loads((isolated/"settings.json").read_text(encoding="utf-8"))
                    if set(data)!={"schemaVersion","schedule","theme","fox","browser","classes","notifications"}: smoke.fail("unexpected_persistent_data")
                    if sorted(p.name for p in isolated.iterdir()) not in (["collector-instance.lock", "settings.json", "settings.lock"],["collector-instance.lock", "settings.json", "settings.lock", "ui-snapshot.json"]): smoke.fail("unexpected_settings_file")
                    snapshot=isolated/"ui-snapshot.json"
                    # The instant-open summary is display data only: never a secret.
                    if snapshot.is_file() and any(word in snapshot.read_text(encoding="utf-8").lower() for word in ("password","senha","token","secret")): smoke.fail("secret_in_ui_snapshot")
                finally:
                    job.close()
                    if process is not None and process.poll() is None: process.kill();process.wait(timeout=10)
            report["other_application_unchanged"]=True
            report["only_nonsecret_settings_retained"]=True
            if report["cleanup"]["verified"]: report["status"]="passed"
    except BaseException as error:
        report["failure"]=str(error) if isinstance(error,smoke.SmokeFailure) else "settings_orchestrator_failed"
        report["error_type"]=type(error).__name__
    smoke.write_json(args.output_dir/"windows-settings-smoke.json",report)
    print(json.dumps({"status":report["status"],"failure":report.get("failure"),"evidence":"windows-settings-smoke.json"}))
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
    if not 10<=args.timeout<=600: parser.error("Invalid timeout")
    if args.worker and not all((args.worker_output,args.settings_directory,args.scenario)): parser.error("Missing internal worker arguments")
    if args.python_executable is not None:
        if args.python_executable.name.lower()!="python.exe": parser.error("Bundled python.exe required")
        args.package_root=args.python_executable.resolve().parent.parent
    args.package_root=args.package_root.resolve();args.output_dir=args.output_dir.resolve()
    return args


if __name__=="__main__":
    options=parse_args()
    raise SystemExit(worker(options) if options.worker else orchestrator(options))

