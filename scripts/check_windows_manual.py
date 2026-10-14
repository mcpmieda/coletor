"""Real portable GUI -> private worker -> separate Edge, with synthetic routing."""
import argparse
import asyncio
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
          'separate_edge_started', 'post_open_synthetic_login_navigation', 'classes_discovered_without_ct', 'selection_persisted_and_revalidated', 'no_student_link_opened', 'reading_requires_consent', 'manual_preview_rendered', 'transmission_blocked',
          'cancelled_result_hidden', 'session_scope_cleared', 'browser_processes_stopped', 'owned_temporaries_removed', 'window_closed']


def synthetic_browser(progress):
    from coletor.demo import build_fixture
    from coletor.origin_proxy import OriginProxy
    import coletor.manual_worker as module
    raw = re.sub(r' data-(?:report|class-id|year|student-count|student-row|report-end)="[^"]*"', '',
                 build_fixture(include_edge_cases=False))
    from coletor.class_catalog import LIST_PATH, ORGANIZATION, SCHOOL
    from urllib.parse import urlsplit, parse_qsl
    def listing(year):
        rows=''.join(f'<tr><td></td><td>{i}</td><td><a href="vinculoAlunoExibirTurma.php?ct={10+i}">{10+i}</a></td><td>Turma sintética {label}</td><td>Etapa sintética</td><td>Matriz sintética</td><td>MATUTINO</td></tr>' for i,label in [(1,'Alpha'),(2,'Beta')])
        return f'<html><head><meta charset="utf-8"><title>Listar Turmas - Ano Letivo {year}</title></head><body>{ORGANIZATION} / {SCHOOL}<a role="combobox">ANO LETIVO: {year}</a><input placeholder="Digite o nome ou parte do nome de uma turma"><table id="tabelaTurmas"><tbody id="tbodyTurmas">{rows}</tbody></table></body></html>'
    original_context, original_page = module.configure_context, module.configure_page
    visits = 0
    captures = 0
    login_received = False
    async def configure_context(context):
        async def fixture(route):
            nonlocal visits, login_received
            if '/qa-only-login' in route.request.url:
                login_received = route.request.method == 'POST' and route.request.post_data == 'SYNTHETIC_LOGIN_ONLY'
                await route.fulfill(status=200, content_type='text/plain', body='synthetic login done')
            elif urlsplit(route.request.url).path == LIST_PATH:
                visits += 1
                if visits == 1:
                    login = """<html><body><input type=password value=SYNTHETIC_ONLY>
                    <button id=qa-sign-in>Entrar com exemplo</button><script>
                    document.querySelector('#qa-sign-in').onclick=()=>fetch('/qa-only-login', {method:'POST',body:'SYNTHETIC_LOGIN_ONLY'}).then(()=>location.href=location.href);
                    setTimeout(()=>document.querySelector('#qa-sign-in').click(),500);
                    </script></body></html>"""
                    await route.fulfill(status=200, content_type='text/html', body=login)
                else:
                    year=int(dict(parse_qsl(urlsplit(route.request.url).query)).get('ano','2026'))
                    await route.fulfill(status=200, content_type='text/html; charset=utf-8', body=listing(year))
                    Path(progress).write_text(json.dumps({'post_open_navigation': True, 'synthetic_login_received': login_received}), encoding='utf-8')
            elif urlsplit(route.request.url).path.endswith('/diario_frequencia.php'):
                await route.fulfill(status=200,content_type='text/html',body=raw)
            else:
                Path(progress).with_name('unexpected-student-navigation.json').write_text('{"unexpected":true}',encoding='utf-8')
                await route.abort()
        await original_context(context, fixture)
    def configure_page(page):
        original_page(page)
        evaluate = page.evaluate
        async def delayed(script):
            nonlocal captures
            if script == module.CAPTURE_JS:
                captures += 1
                if captures == 2:
                    Path(progress).with_name('second-capture-started.json').write_text('{"started":true}', encoding='utf-8')
                await asyncio.sleep(1)
            return await evaluate(script)
        page.evaluate = delayed
    def no_network():
        raise OSError('synthetic_upstream_forbidden')
    module.OriginProxy = lambda: OriginProxy(dial=no_network)
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
            return [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--browser-worker', '--progress', str(args.output.parent / 'post-open-navigation.json')]
    original = DesktopApi.__init__
    def initialize(api, *a, **kw):
        original(api, *a, **kw)
        def factory():
            driver = FixtureBrowser()
            drivers.append(driver)
            return driver
        api._manual_session._factory = factory
    DesktopApi.__init__ = initialize
    lock_spec = importlib.util.spec_from_file_location('qa_locks', Path(__file__).with_name('qa_lock_diagnostic.py'))
    lock_module = importlib.util.module_from_spec(lock_spec)
    lock_spec.loader.exec_module(lock_module)
    def exercise(window):
        try:
            checks['native_window_visible'] = bool(window.native.Visible)
            alpha="[...document.querySelectorAll('input')].find(n=>n.getAttribute('aria-label')==='Selecionar Turma sintética Alpha')"
            year_ready="(()=>{const label=[...document.querySelectorAll('label')].find(n=>n.textContent.trim()==='Ano letivo no Smecel');return document.getElementById(label?.htmlFor)?.disabled===false;})()"
            smoke.wait_js(window, '!!window.pywebview?.api.prepare_manual_login')
            checks['prepared_without_browser']=not drivers
            checks['opening_requires_consent']=window.evaluate_js("[...document.querySelectorAll('button')].find(n=>n.textContent.trim()==='Entrar no Smecel')?.disabled===true")
            controls.checkbox(window,'Autorizo abrir o Smecel e ler a lista de turmas deste ano, sem envio.')
            controls.click(window,'Entrar no Smecel')
            smoke.wait_js(window,"[...document.querySelectorAll('button')].some(n=>n.textContent.trim()==='Carregar turmas'&&!n.disabled)",50)
            checks['separate_edge_started']=len(drivers)==1 and drivers[0]._process is not None
            progress=args.output.parent/'post-open-navigation.json'
            deadline=time.monotonic()+20
            while not progress.exists() and time.monotonic()<deadline:time.sleep(0.05)
            proof=json.loads(progress.read_text(encoding='utf-8')) if progress.exists() else {}
            checks['post_open_synthetic_login_navigation']=proof=={'post_open_navigation':True,'synthetic_login_received':True}
            if not checks['post_open_synthetic_login_navigation']:smoke.fail('post_open_navigation_blocked_before_capture')
            controls.click(window,'Carregar turmas')
            smoke.wait_js(window,alpha)
            checks['classes_discovered_without_ct']=not window.evaluate_js("document.body.textContent.includes('Código numérico da turma no Smecel')")
            window.evaluate_js(alpha+".click();true")
            smoke.wait_js(window,"[...document.querySelectorAll('option')].some(n=>n.value==='11') && !document.querySelector('fieldset.class-choices').disabled")
            controls.click(window,'Encerrar sessão e descartar prévia')
            smoke.wait_js(window,year_ready)
            progress.unlink(missing_ok=True)
            controls.checkbox(window,'Autorizo abrir o Smecel e ler a lista de turmas deste ano, sem envio.')
            controls.click(window,'Entrar no Smecel')
            smoke.wait_js(window,"[...document.querySelectorAll('button')].some(n=>n.textContent.trim()==='Carregar turmas'&&!n.disabled)",50)
            deadline=time.monotonic()+20
            while not progress.exists() and time.monotonic()<deadline:time.sleep(0.05)
            if not progress.exists():smoke.fail('second_login_not_completed')
            controls.click(window,'Carregar turmas')
            smoke.wait_js(window,alpha+"?.checked")
            stored=json.loads((args.output.parent/'settings/class-selection.json').read_text(encoding='utf-8'))
            checks['selection_persisted_and_revalidated']=stored['profiles'][0]['selected_class_ids']==['11'] and set(stored)=={'schemaVersion','localRevision','profiles'}
            checks['reading_requires_consent']=window.evaluate_js("[...document.querySelectorAll('button')].find(n=>n.textContent.trim()==='Ler diário manualmente')?.disabled===true")
            consent='Autorizo ler o diário desta turma e deste ano para uma prévia local, sem envio.'
            controls.checkbox(window,consent)
            controls.click(window,'Ler diário manualmente')
            smoke.wait_js(window,"document.body.textContent.includes('Prévia da turma') && document.body.textContent.includes('Leitura manual do Smecel')")
            checks['manual_preview_rendered']=True
            checks['transmission_blocked']=window.evaluate_js("document.body.textContent.includes('Envio desativado') && document.body.textContent.includes('Não envia dados')")
            checks['no_student_link_opened']=not (args.output.parent/'unexpected-student-navigation.json').exists()
            window.evaluate_js("""(() => {
              const api=window.pywebview.api, close=api.close_manual_session.bind(api);
              api.close_manual_session=(...args)=>close(...args).then(r=>{
                window.__closeDiagnosis={ok:!('error' in r),state:r.state??null,pending:r.cleanup_pending??null,message:r.error??null};return r;
              });return true;
            })()""")
            controls.checkbox(window, consent)
            controls.click(window, 'Ler diário manualmente')
            capture_marker = args.output.parent / 'second-capture-started.json'
            deadline = time.monotonic() + 10
            while not capture_marker.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not capture_marker.exists():
                smoke.fail('second_capture_not_started')
            cancel_started = time.monotonic()
            controls.click(window, 'Encerrar sessão e descartar prévia')
            smoke.wait_js(window, "!document.body.textContent.includes('Prévia da turma') && "+year_ready)
            report['cancel_elapsed_ms'] = round((time.monotonic() - cancel_started) * 1000)
            time.sleep(1.5)
            checks['cancelled_result_hidden'] = window.evaluate_js("!document.body.textContent.includes('Prévia da turma')")
            window.evaluate_js("window.__manualStatus=null;window.pywebview.api.get_manual_session_status().then(r=>window.__manualStatus=r);true")
            smoke.wait_js(window, '!!window.__manualStatus')
            checks['session_scope_cleared'] = window.evaluate_js("window.__manualStatus.state==='closed' && window.__manualStatus.scope===null")
            checks['browser_processes_stopped'] = all(d.cleanup and d.cleanup['verified'] for d in drivers)
            checks['owned_temporaries_removed'] = all(d._temporary is None for d in drivers)
            report['status'] = 'passed' if all(checks.values()) else 'failed'
        except BaseException as error:
            report['failure'] = str(error) if isinstance(error, smoke.SmokeFailure) else 'manual_native_worker_failed'
            report['diagnostic'] = window.evaluate_js("""(() => ({
              previewVisible: document.body.textContent.includes('Prévia da turma'),
              prepareDisabled: [...document.querySelectorAll('button')].find(n=>n.textContent.trim()==='Entrar no Smecel')?.disabled ?? null,
              closeVisible: [...document.querySelectorAll('button')].some(n=>n.textContent.trim()==='Encerrar sessão e descartar prévia'),
              errorVisible: !!document.querySelector('.error-message'),
            }))()""")
            report['driver_diagnostic'] = [{'stopped': d._process is None,
                                          'cleanup_verified': bool(d.cleanup and d.cleanup['verified']),
                                          'temporary_removed': d._temporary is None,
                                          'temporary_error_codes': getattr(d, '_cleanup_errors', [])} for d in drivers]
            report['close_diagnostic'] = window.evaluate_js('window.__closeDiagnosis ?? null')
            report['temporary_lock_diagnostic'] = lock_module.locks(getattr(drivers[0], '_temp_failed_path', None))
        finally:
            window.destroy()
    try:
        checks['bundled_application'] = Path(desktop.__file__).resolve().parents[2] == program
        desktop.run_desktop(callback=exercise, settings_directory=args.output.parent / 'settings', access=smoke.synthetic_institutional_access())
        checks['window_closed'] = True
    except BaseException:
        report['status'] = 'failed'
    args.output.write_text(json.dumps(report), encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1


def main():
    if '--browser-worker' in sys.argv:
        synthetic_browser(sys.argv[sys.argv.index('--progress') + 1])
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
