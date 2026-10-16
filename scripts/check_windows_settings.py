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


def click(window,label):
    expression="""(() => {const label=%s; const n=[...document.querySelectorAll('button')].find(n=>n.textContent.trim()===label || n.getAttribute('aria-label')===label); if(!n||n.disabled)return false;n.click();return true;})()""" % json.dumps(label)
    if not window.evaluate_js(expression): smoke.fail("settings_button_unavailable")


def set_input(window,label,value):
    expression="""(() => {const label=[...document.querySelectorAll('label')].find(n=>n.textContent.trim()===%s);const n=document.getElementById(label?.htmlFor);if(!n||n.disabled)return false;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(n,%s);n.dispatchEvent(new Event('input',{bubbles:true}));return true;})()""" % (json.dumps(label),json.dumps(value))
    if not window.evaluate_js(expression): smoke.fail("settings_input_unavailable")


def monday_js(value):
    return """(() => {const label=[...document.querySelectorAll('label')].find(n=>n.textContent.trim()==='Buscar frequência Segunda-feira Manhã');return document.getElementById(label?.htmlFor)?.value.startsWith(%s);})()""" % json.dumps(value)


def checkbox(window,label):
    expression="""(() => {const n=[...document.querySelectorAll('label')].find(n=>n.textContent.trim()===%s)?.querySelector('input');if(!n||n.disabled)return false;n.click();return true;})()""" % json.dumps(label)
    if not window.evaluate_js(expression): smoke.fail("settings_checkbox_unavailable")


def theme(window,label):
    expression="""(() => {const n=[...document.querySelectorAll('button')].find(n=>(n.getAttribute('aria-labelledby')||'').split(' ').some(id=>document.getElementById(id)?.textContent.trim()==='Tema'));if(!n)return false;n.click();return true;})()"""
    if not window.evaluate_js(expression): smoke.fail("theme_trigger_unavailable")
    smoke.wait_js(window,"!!document.querySelector('[role=option]')")
    expression="""(() => {const n=[...document.querySelectorAll('[role=option]')].find(n=>n.textContent.trim()===%s);if(!n)return false;n.click();return true;})()""" % json.dumps(label)
    if not window.evaluate_js(expression): smoke.fail("theme_option_unavailable")


def stored(window,predicate):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        window.evaluate_js("window.__localSettingsProbe=null;Promise.all([window.pywebview.api.get_local_settings(),window.pywebview.api.get_collector_status()]).then(([r,c])=>{if(c.settings?.schedule)r.settings.schedule={rules:c.settings.schedule.rules.map(v=>({...v,weekday:v.weekday===0?7:v.weekday,selected:v.enabled,reconciliation:v.recheck||''})).sort((a,b)=>a.weekday-b.weekday||a.shift.localeCompare(b.shift))};window.__localSettingsProbe=r;});true")
        smoke.wait_js(window,"!!window.__localSettingsProbe",timeout=10)
        result=window.evaluate_js("window.__localSettingsProbe")
        if predicate(result): return result
        time.sleep(.1)
    smoke.fail("settings_disk_acknowledgement_timeout")


def exercise(window,args,result):
    checks=result["checks"]
    def require(name,value=True):
        if not value: smoke.fail(name)
        checks[name]=True
    try:
        smoke.wait_js(window,"[...document.querySelectorAll('button')].some(n=>n.textContent.trim()==='Horários de coleta'&&!n.disabled) && typeof window.pywebview?.api?.get_local_settings==='function'")
        info,handle=smoke.native_info(window)
        require("native_window_visible",info["visible"] and info["edgechromium"])
        click(window,"Horários de coleta")
        smoke.wait_js(window,monday_js("08:"))
        if args.scenario=="save":
            require("fresh_default_schedule",window.evaluate_js(monday_js("08:05")))
            set_input(window,"Buscar frequência Segunda-feira Manhã","08:15, 09:00, 09:55, 11:05, 11:55")
            click(window,"Salvar horários")
            smoke.wait_js(window,"document.body.innerText.includes('Horários compartilhados com os computadores da escola.')")
            theme(window,"Escuro")
            smoke.wait_js(window,"document.documentElement.dataset.theme==='dark'")
            stored(window,lambda r:r.get("settings",{}).get("schedule",{}).get("rules",[{}])[0].get("times",[None])[0]=="08:15"
                   and r["settings"]["theme"]=="dark")
            require("agenda_and_theme_saved_to_disk")
        elif args.scenario=="reopen":
            require("agenda_survives_normal_close",window.evaluate_js(monday_js("08:15")))
            require("theme_survives_normal_close",window.evaluate_js("document.documentElement.dataset.theme==='dark'"))
            require("fox_always_shown",window.evaluate_js("!!document.querySelector('.fox-stage')"))
            click(window,"Usar sugestão")
            smoke.wait_js(window,monday_js("08:05"))
            stored(window,lambda r:r["settings"]["schedule"]["rules"][0]["times"][0]=="08:15")
            require("restore_does_not_save_implicitly")
            click(window,"Salvar horários")
            stored(window,lambda r:r["settings"]["schedule"]["rules"][0]["times"][0]=="08:05")
            require("restored_schedule_saved")
        elif args.scenario=="restored":
            require("restored_schedule_survives_close",window.evaluate_js(monday_js("08:05")))
            require("other_preferences_preserved",window.evaluate_js("document.documentElement.dataset.theme==='dark' && !!document.querySelector('.fox-stage')"))
        else:
            require("corrupt_file_defaults_visible",window.evaluate_js(monday_js("08:05")))
            require("corrupt_file_notice_visible",window.evaluate_js("document.querySelector('.local-settings-notice')?.textContent.includes('Não foi possível ler')"))
            require("corrupt_file_restores_nonsecret_preferences",window.evaluate_js("document.querySelector('.fox-stage')!==null"))
            click(window,"Salvar horários")
            theme(window,"Escuro")
            stored(window,lambda r:not r.get("notice") and r["settings"]["schedule"]["rules"][0]["times"][0]=="08:05")
            smoke.wait_js(window,"!document.querySelector('.local-settings-notice')")
            require("explicit_save_recovers_valid_file_and_clears_notice")
        window.evaluate_js("window.scrollTo(0,0)")
        result["screenshot"]=smoke.capture_window(handle,args.output_dir/("settings-"+args.scenario+".png"))
        result["status"]="passed"
    except Exception as error:
        result["status"]="failed"
        result["failure"]=str(error) if isinstance(error,smoke.SmokeFailure) else "settings_window_check_failed"
        result["error_type"]=type(error).__name__
    finally:
        smoke.write_json(args.worker_output,result)
        window.destroy()


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
                    if set(data)!={"schemaVersion","schedule","theme","fox"}: smoke.fail("unexpected_persistent_data")
                    if sorted(p.name for p in isolated.iterdir())!=["collector-instance.lock", "settings.json", "settings.lock"]: smoke.fail("unexpected_settings_file")
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

