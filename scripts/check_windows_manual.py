"""Real portable GUI -> private worker -> separate Edge, with synthetic routing."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

spec = importlib.util.spec_from_file_location('smoke', Path(__file__).with_name('check_windows_portable.py'))
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
spec = importlib.util.spec_from_file_location('settings_smoke', Path(__file__).with_name('check_windows_settings.py'))
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)
CHECKS = ['bundled_application', 'native_window_visible', 'prepared_without_browser', 'opening_requires_consent',
          'separate_edge_started', 'reading_requires_consent', 'manual_preview_rendered', 'transmission_blocked',
          'cancelled_result_hidden', 'session_scope_cleared', 'browser_processes_stopped', 'window_closed']


def synthetic_browser():
    from coletor.demo import build_fixture
    import coletor.manual_worker as module
    raw = re.sub(r' data-(?:report|class-id|year|student-count|student-row|report-end)="[^"]*"', '',
                 build_fixture(include_edge_cases=False))
    original_context, original_page = module.configure_context, module.configure_page
    def configure_context(context):
        original_context(context, lambda route: route.fulfill(status=200, content_type='text/html', body=raw))
    def configure_page(page):
        original_page(page)
        evaluate = page.evaluate
        def delayed(script):
            if script == module.CAPTURE_JS:
                time.sleep(1)
            return evaluate(script)
        page.evaluate = delayed
    module.configure_context, module.configure_page = configure_context, configure_page
    module.main()


def worker(args):
    if sys.stdin.readline().strip() != 'RUN':
        return 2
    from coletor.desktop_api import DesktopApi
    from coletor.manual_worker import BrowserWorker
    import coletor.desktop as desktop
    program = args.python.resolve().parent
    report = {'status': 'failed', 'checks': {}}
    checks = report['checks']
    drivers = []
    class FixtureBrowser(BrowserWorker):
        def _command(self):
            return [sys.executable, '-I', str(Path(__file__).resolve()), '--browser-worker']
    original = DesktopApi.__init__
    def initialize(api, *a, **kw):
        original(api, *a, **kw)
        def factory():
            driver = FixtureBrowser()
            drivers.append(driver)
            return driver
        api._manual_session._factory = factory
    DesktopApi.__init__ = initialize
    def exercise(window):
        try:
            checks['native_window_visible'] = bool(window.native.Visible)
            smoke.wait_js(window, '!!window.pywebview?.api.prepare_manual_session')
            controls.set_input(window, 'Código numérico da turma no Smecel', '13331')
            controls.click(window, 'Preparar sessão')
            smoke.wait_js(window, "document.body.textContent.includes('Sessão preparada, sem acesso ao site.')")
            checks['prepared_without_browser'] = not drivers
            checks['opening_requires_consent'] = window.evaluate_js("[...document.querySelectorAll('button')].find(n=>n.textContent.trim()==='Abrir Smecel')?.disabled === true")
            controls.checkbox(window, 'Autorizo abrir esta turma e este ano no Smecel e fazer o login diretamente no site.')
            controls.click(window, 'Abrir Smecel')
            smoke.wait_js(window, "[...document.querySelectorAll('button')].some(n=>n.textContent.trim()==='Ler diário manualmente')", 50)
            checks['separate_edge_started'] = len(drivers) == 1 and drivers[0]._process is not None
            checks['reading_requires_consent'] = window.evaluate_js("[...document.querySelectorAll('button')].find(n=>n.textContent.trim()==='Ler diário manualmente')?.disabled === true")
            consent = 'Conferi a turma e o ano na janela separada e autorizo ler este diário para uma prévia local, sem envio.'
            controls.checkbox(window, consent)
            controls.click(window, 'Ler diário manualmente')
            smoke.wait_js(window, "document.body.textContent.includes('Prévia da turma') && document.body.textContent.includes('Leitura manual do Smecel')")
            checks['manual_preview_rendered'] = True
            checks['transmission_blocked'] = window.evaluate_js("document.body.textContent.includes('Envio desativado') && document.body.textContent.includes('Não envia dados')")
            controls.checkbox(window, consent)
            controls.click(window, 'Ler diário manualmente')
            controls.click(window, 'Encerrar sessão e descartar prévia')
            smoke.wait_js(window, "!document.body.textContent.includes('Prévia da turma') && [...document.querySelectorAll('button')].some(n=>n.textContent.trim()==='Preparar sessão' && !n.disabled)")
            time.sleep(1.5)
            checks['cancelled_result_hidden'] = window.evaluate_js("!document.body.textContent.includes('Prévia da turma')")
            window.evaluate_js("window.__manualStatus=null;window.pywebview.api.get_manual_session_status().then(r=>window.__manualStatus=r);true")
            smoke.wait_js(window, '!!window.__manualStatus')
            checks['session_scope_cleared'] = window.evaluate_js("window.__manualStatus.state==='closed' && window.__manualStatus.scope===null")
            checks['browser_processes_stopped'] = all(d.cleanup and d.cleanup['verified'] for d in drivers)
            report['status'] = 'passed' if all(checks.values()) else 'failed'
        except BaseException as error:
            report['failure'] = str(error) if isinstance(error, smoke.SmokeFailure) else 'manual_native_worker_failed'
        finally:
            window.destroy()
    try:
        checks['bundled_application'] = Path(desktop.__file__).resolve().parents[2] == program
        desktop.run_desktop(callback=exercise, settings_directory=args.output.parent / 'settings')
        checks['window_closed'] = True
    except BaseException:
        report['status'] = 'failed'
    args.output.write_text(json.dumps(report), encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1


def main():
    if '--browser-worker' in sys.argv:
        synthetic_browser()
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        return worker(args)
    args.python, args.output = args.python.resolve(), args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    job = smoke.WindowsJob()
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='coletor-native-manual-') as directory:
            result = Path(directory) / 'result.json'
            command = [str(args.python), '-I', str(Path(__file__).resolve()), '--worker', '--python', str(args.python), '--output', str(result)]
            process = subprocess.Popen(command, cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            job.assign(process.pid)
            process.communicate(b'RUN\n', timeout=130)
            cleanup = job.finish(grace=0 if process.poll() is None else 5)
            report = json.loads(result.read_text(encoding='utf-8')) if result.exists() else {'status': 'failed', 'checks': {}}
            report.update(cleanup=cleanup, real_network=False, real_credentials=False)
            if process.returncode != 0 or not cleanup['verified'] or not all(report['checks'].get(k) is True for k in CHECKS):
                report['status'] = 'failed'
            args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps({'status': report['status'], 'evidence': args.output.name}))
            return 0 if report['status'] == 'passed' else 1
    finally:
        job.close()
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(5)


if __name__ == '__main__':
    raise SystemExit(main())
