"""Local Chromium smoke test. Uses synthetic data only, without external sites."""
import json
import os
from pathlib import Path
import threading
from playwright.sync_api import expect, sync_playwright
from coletor.server import PreviewServer

server = PreviewServer(0)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
url = f'http://127.0.0.1:{server.server_address[1]}'
root = Path(__file__).resolve().parents[1]
out = Path(os.environ.get('QA_OUTPUT', '/tmp/smecel-qa'))
out.mkdir(parents=True, exist_ok=True)
errors = []
atlas_requests = []
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', p.chromium.executable_path), headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1440,'height':1000}, locale='pt-BR', color_scheme='light', reduced_motion='reduce')
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda r: atlas_requests.append(r.url) if r.url.endswith('/mascot/atlas.png') else None)
        page.goto(url)
        page.get_by_role('heading', name='Vamos conferir a frequência?').wait_for()
        version = json.loads((root / 'ui/package.json').read_text(encoding='utf-8'))['version']
        expect(page.get_by_text(f'Versão {version}', exact=True)).to_be_visible()
        fox = page.get_by_role('img', name='Raposa vermelha, mascote do coletor')
        fox.wait_for()
        expect(fox).to_have_js_property('complete', True)
        assert fox.evaluate('img => img.complete && img.naturalWidth > 0'), 'Missing fox sprite'
        assert page.locator('.fox-stage').get_attribute('data-motion') == 'off'
        assert page.locator('.fox-button').evaluate('el => getComputedStyle(el).animationName') == 'none'
        assert page.get_by_role('checkbox', name='Mostrar raposa').count() == 0
        page.emulate_media(reduced_motion='no-preference')
        page.locator('.fox-stage[data-motion=on]').wait_for()
        expect(fox).to_have_js_property('complete', True)
        atlas_count = len(atlas_requests)
        page.get_by_role('button',name='Fazer carinho na raposa').click()
        assert page.locator('.fox-stage').get_attribute('data-action') == 'pet'
        expect(page.locator('.fox-stage')).to_have_attribute('data-pose', 'happy')
        assert len(atlas_requests) == atlas_count, 'Sprite animation fetched another image'
        page.emulate_media(reduced_motion='reduce')
        page.locator('.fox-stage[data-motion=off]').wait_for()
        assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()") == '#a32743'
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'empty-light.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='Usar dados de exemplo').click()
        page.get_by_role('heading', name='Prévia da turma').wait_for()
        assert page.get_by_text('Aluno sintético 001',exact=True).count() > 0
        assert page.get_by_text('Envio desativado',exact=True).is_visible()
        assert page.title(), 'Page identity missing'
        assert page.locator('vite-error-overlay').count() == 0

        assert page.locator('tbody tr').count() == 24
        details = page.locator('.checks details')
        assert details.get_attribute('open') is None
        assert 'studentUid' not in page.locator('.checks').inner_text()
        details.locator('summary').click()
        assert details.get_attribute('open') is not None
        details.locator('summary').click()
        assert details.get_attribute('open') is None
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'demo-light.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='Próxima página').click()
        assert 'Página 2 de' in page.locator('.table-footer').inner_text()
        page.get_by_role('button', name='Página anterior').click()
        assert 'Página 1 de' in page.locator('.table-footer').inner_text()
        # HeroUI uses an accessible select trigger and listbox.
        page.get_by_role('button', name='Aluno').click()
        page.get_by_role('option', name='Aluno sintético 002', exact=True).click()
        assert all('Aluno sintético 002' in row for row in page.locator('tbody tr').all_inner_texts())
        page.get_by_role('button', name='Tema').click()
        page.get_by_role('option', name='Escuro', exact=True).click()
        page.get_by_role('listbox').wait_for(state='hidden')
        assert page.locator('html').get_attribute('data-theme') == 'dark'
        assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()") == '#f28ba0'
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'demo-dark.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='Horários de coleta', exact=True).click()
        page.get_by_role('heading', name='Dias e horários').wait_for()
        page.get_by_role('button', name='Conferir frequência', exact=True).click()
        page.get_by_role('heading', name='Prévia da turma').wait_for()
        page.get_by_role('button', name='Fechar diário').click()
        page.get_by_role('heading', name='Vamos conferir a frequência?').wait_for()
        page.get_by_label('Selecionar arquivo do diário').set_input_files(str(root/'fixtures/annual-synthetic.html'))
        page.get_by_role('heading', name='Prévia da turma').wait_for()
        assert page.get_by_text('Arquivo deste computador', exact=False).count() == 1
        page.get_by_role('button', name='Fechar diário').click()
        page.get_by_label('Selecionar arquivo do diário').set_input_files({'name':'invalid.html','mimeType':'text/html','buffer':b'<html><form>login</form></html>'})
        page.get_by_role('heading', name='Prévia da turma').wait_for()
        assert page.get_by_text('Envio desativado',exact=True).is_visible()
        assert page.title(), 'Page identity missing'
        assert page.locator('vite-error-overlay').count() == 0

        # School schedule remains a local preview: edit, validate, save, reload, undo.
        page.get_by_role('button', name='Horários de coleta', exact=True).click()
        page.get_by_role('heading', name='Dias e horários').wait_for()
        assert page.get_by_text('Por enquanto, os horários ficam só neste computador.', exact=False).is_visible()
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'schedule-initial.png'), full_page=True, animations='disabled')
        assert page.get_by_label('Fuso horário da escola').input_value() == 'America/Bahia'
        about = page.locator('.schedule-page details')
        assert about.get_attribute('open') is None
        about.locator('summary').click()
        assert page.get_by_text('Depois, usuários e computadores autorizados poderão usar os mesmos horários.', exact=False).is_visible()
        about.locator('summary').click()
        assert page.get_by_label('Buscar frequência Sexta-feira Manhã', exact=True).input_value().startswith('08:40')
        assert not page.get_by_role('checkbox', name='Incluir Sábado Manhã').is_checked()
        monday = page.get_by_label('Buscar frequência Segunda-feira Manhã', exact=True)
        monday.fill('24:00')
        page.get_by_role('button', name='Salvar horários', exact=True).click()
        assert page.get_by_role('alert').is_visible()
        monday.fill('08:15, 09:00, 09:55, 11:05, 11:55')
        page.get_by_role('button', name='Salvar horários', exact=True).click()
        assert page.get_by_role('status').filter(has_text='Horários salvos só neste computador.').is_visible()
        page.reload()
        page.get_by_role('button', name='Horários de coleta', exact=True).click()
        monday = page.get_by_label('Buscar frequência Segunda-feira Manhã', exact=True)
        assert monday.input_value().startswith('08:15')
        monday.fill('08:30')
        page.get_by_role('button', name='Conferir frequência', exact=True).click()
        page.get_by_role('button', name='Horários de coleta', exact=True).click()
        assert monday.input_value() == '08:30', 'Draft lost on navigation'
        page.get_by_role('button', name='Desfazer alterações', exact=True).click()
        assert monday.input_value().startswith('08:15')
        page.get_by_role('button', name='Tarde', exact=True).click()
        assert page.get_by_label('Conferir no fim Sexta-feira Tarde', exact=True).input_value() == '18:30'
        page.get_by_role('button', name='Usar sugestão', exact=True).click()
        page.get_by_role('button', name='Salvar horários', exact=True).click()
        page.get_by_role('button', name='Manhã', exact=True).click()
        assert monday.input_value().startswith('08:05')
        page.set_viewport_size({'width':1240,'height':820})
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'schedule-dark.png'), full_page=True, animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Schedule desktop overflow'
        page.get_by_role('button', name='Tema').click()
        page.get_by_role('option', name='Claro', exact=True).click()
        page.get_by_role('listbox').wait_for(state='hidden')
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'schedule-light.png'), full_page=True, animations='disabled')
        page.set_viewport_size({'width':390,'height':844})
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'schedule-mobile.png'), full_page=True, animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Schedule mobile overflow'
        page.get_by_role('button', name='Conferir frequência', exact=True).click()
        # Repeated load after error and clearing; no stale preview.
        page.get_by_role('button', name='Usar dados de exemplo').click()
        page.get_by_role('heading', name='Prévia da turma').wait_for()
        page.set_viewport_size({'width':1240,'height':820})
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'desktop-window.png'), full_page=True, animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Desktop-window overflow'
        page.set_viewport_size({'width':390,'height':844})
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'mobile.png'), full_page=True, animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Horizontal page overflow'
        assert page.get_by_role('button',name='Abrir diário').is_visible()
        # AUD-004: the same diagnostic on separate cards remains identifiable.
        page.set_viewport_size({'width':1440,'height':1000})
        from coletor.demo import build_fixture
        html = build_fixture(include_edge_cases=False).replace('<div>1</div><div>2</div>','<div>2</div><div>1</div>')
        page.get_by_label('Selecionar arquivo do diário').set_input_files({'name':'synthetic-diagnostics.html','mimeType':'text/html','buffer':html.encode()})
        page.get_by_role('heading',name='Prévia da turma').wait_for()
        details=page.locator('.checks details'); details.locator('summary').click()
        details.get_by_role('combobox').select_option('LESSON_HEADER_INVALID')
        assert 'row:1' in details.inner_text() and 'row:2' in details.inner_text()
        page.screenshot(path=str(out/'diagnostics-by-card.png'),full_page=True,animations='disabled')
        details.locator('summary').click()
        # AUD-010: discard the result but stay busy until native work ends.
        page.get_by_role('button',name='Fechar diário').click()
        demo=page.request.get(url+'/api/demo').json()
        page.evaluate("window.pywebview={api:{load_demo:()=>new Promise(resolve=>{window.finishSyntheticRead=resolve;})}}")
        page.get_by_role('button',name='Usar dados de exemplo').click()
        page.get_by_role('button',name='Descartar resultado').wait_for()
        page.get_by_role('button',name='Descartar resultado').click()
        expect(page.get_by_role('button',name='Usar dados de exemplo')).to_be_disabled()
        expect(page.get_by_role('button',name='Abrir diário')).to_be_disabled()
        page.evaluate('value => window.finishSyntheticRead(value)',demo)
        expect(page.get_by_role('button',name='Usar dados de exemplo')).to_be_enabled()
        assert page.get_by_role('heading',name='Prévia da turma').count()==0
        page.get_by_role('heading',name='Vamos conferir a frequência?').wait_for()
        page.evaluate('delete window.pywebview; delete window.finishSyntheticRead')
        assert not errors, errors
        # Independent review: recovery notice and pending reload/edit/save race.
        import json as json_module
        config = {'schemaVersion':1,'scope':'school','storageMode':'local-preview','localRevision':0,'sharedRevision':None,'timezone':'America/Bahia','rules':json_module.loads((root/'ui/src/schedule-presets.json').read_text(encoding='utf-8'))['rules']}
        prefs = {'schemaVersion':1,'schedule':config,'theme':'light','fox':{'version':1,'show':True,'animate':False}}
        recovery_page=browser.new_page(viewport={'width':1440,'height':1000},locale='pt-BR')
        recovery_page.on('pageerror',lambda error: errors.append(str(error)))
        shared = {'timezone': 'America/Bahia', 'rules': [{'weekday': r['weekday'] % 7, 'shift': r['shift'],
                  'enabled': r['selected'], 'times': r['times'], 'recheck': r['reconciliation'] or None} for r in config['rules']]}
        # A uniform fixture exercises the simple editor; heterogeneous rules are tested separately below.
        for rule in shared['rules']:
            rule.update(times=['07:00', '07:30', '08:00'] if rule['enabled'] else [], recheck=None)
        collector = {'state': 'connect', 'code': None, 'active': False, 'localPaused': False, 'persistent': False,
                     'progress': {'completed': 0, 'total': 0, 'classLabel': None}, 'lastReceipt': None,
                     'settings': {'revision': 2, 'paused': False, 'schedule': shared}}
        recovery_init = 'window.syntheticSettings='+json_module.dumps({**prefs,'browser':{'visible':False},'classes':{'mode':'all'}})+';window.syntheticCollector='+json_module.dumps(collector)+''';
          window.syntheticSaves=[];window.syntheticConflict=true;
          window.pywebview={api:{get_institutional_access_status:async()=>({authenticated:true,authorized:true}),
            open_institutional_login:async()=>({ok:true}),logout_institutional_access:async()=>({ok:true}),
            get_local_recovery_status:async()=>({pending:false,count:0,oldest:null,newest:null,unreadable:false}),
            discard_local_pending_collection:async()=>({ok:true,discarded:false}),
            get_startup_snapshot:async()=>({paired:true,status:window.syntheticCollector,history:[],settings:window.syntheticSettings}),
            get_local_settings:async()=>({settings:window.syntheticSettings}),
            get_collector_status:async()=>window.syntheticCollector,
            get_collector_history:async()=>({entries:[]}),
            get_desktop_status:async()=>({tray_available:true,automatic_collection:true,autostart:true}),
            activate_collector:async()=>window.syntheticCollector,collect_now:async()=>window.syntheticCollector,
            save_shared_schedule:async(revision,schedule)=>{if(window.syntheticConflict)return {error:'Conflito',code:'revision-conflict'};
              if(revision!==window.syntheticCollector.settings.revision)return {error:'Conflito',code:'revision-conflict'};
              window.syntheticSaves.push(schedule);window.syntheticCollector.settings={revision:revision+1,paused:false,schedule};return window.syntheticCollector;}}};'''
        recovery_page.add_init_script(recovery_init)
        recovery_page.goto(url)
        # Desktop shell: four sidebar pages, agenda edited by periods in Tarefas.
        nav = recovery_page.get_by_role('navigation', name='Navegação principal')
        for label in ('Histórico', 'Registros', 'Ajustes', 'Tarefas'):
            nav.get_by_role('button', name=label, exact=True).click()
            expect(nav.get_by_role('button', name=label, exact=True)).to_have_attribute('aria-current', 'page')
        recovery_page.get_by_role('button', name='Editar agenda', exact=True).click()
        recovery_page.get_by_role('heading', name='Agenda de coleta').wait_for()
        recovery_page.get_by_label('Quando coletar').click()
        recovery_page.get_by_role('option', name='Em horários fixos').click()
        # Fixed times are time fields for the whole day: clear them, then add three.
        remove = recovery_page.locator('[role=dialog] button[aria-label^="Remover horário"]')
        while remove.count():
            remove.first.click()
        for _ in range(3):
            recovery_page.get_by_role('button', name='Adicionar horário').click()
        expect(remove).to_have_count(3)
        def type_time(target, index, hour, minute):
            field = target.get_by_role('group', name=f'Horário {index}', exact=True)
            segments = field.get_by_role('spinbutton')
            for segment, value in ((segments.nth(0), hour), (segments.nth(1), minute)):
                segment.click(); segment.press_sequentially(value)
        for index, hour, minute in ((1, '08', '15'), (2, '09', '00'), (3, '09', '55')):
            type_time(recovery_page, index, hour, minute)
        save = recovery_page.get_by_role('button', name='Salvar', exact=True)
        recovery_page.get_by_role('group', name='Horário 2', exact=True).get_by_role('spinbutton').first.press('Backspace')
        expect(save).to_be_disabled()
        expect(recovery_page.get_by_text('Preencha ou remova o horário incompleto.', exact=True)).to_be_visible()
        assert recovery_page.evaluate('window.syntheticSaves.length') == 0
        type_time(recovery_page, 2, '08', '15')
        expect(save).to_be_disabled()
        type_time(recovery_page, 2, '08', '18')
        expect(save).to_be_disabled()
        type_time(recovery_page, 2, '09', '00')
        if save.is_disabled():
            raise AssertionError('Agenda save blocked: ' + recovery_page.get_by_role('dialog').inner_text()[-300:])
        recovery_page.get_by_role('button', name='Salvar', exact=True).click()
        expect(recovery_page.get_by_text('A agenda mudou em outro computador. Feche e abra de novo para ver a versão atual.', exact=True)).to_be_visible()
        expect(remove).to_have_count(3)  # The draft survives the conflict.
        recovery_page.evaluate('window.syntheticConflict=false')
        recovery_page.get_by_role('button', name='Salvar', exact=True).click()
        recovery_page.get_by_role('heading', name='Agenda de coleta').wait_for(state='hidden')
        assert recovery_page.evaluate('window.syntheticSaves.length') == 1
        written = recovery_page.evaluate('window.syntheticSaves[0]')
        active = [r for r in written['rules'] if r['enabled']]
        expected_keys = {(r['weekday'], r['shift']) for r in shared['rules'] if r['enabled']}
        assert len(active) == len(expected_keys) > 0
        assert {(r['weekday'], r['shift']) for r in active} == expected_keys
        assert all(r['times'] == ['08:15', '09:00', '09:55'] and r['recheck'] is None for r in active)
        assert written['timezone'] == shared['timezone']
        recovery_page.screenshot(path=str(out/'schedule-recovery-after-save.png'),full_page=True,animations='disabled')
        recovery_page.get_by_role('button', name='Editar agenda', exact=True).click()
        recovery_page.get_by_role('button', name='Adicionar horário', exact=True).click()
        last_field = recovery_page.get_by_role('group', name='Horário 4', exact=True).get_by_role('spinbutton')
        last_field.nth(0).press('Backspace'); last_field.nth(0).press('Backspace')
        last_field.nth(1).press('Backspace'); last_field.nth(1).press('Backspace')
        expect(recovery_page.get_by_role('button', name='Salvar', exact=True)).to_be_disabled()
        recovery_page.get_by_role('button', name='Cancelar', exact=True).click()
        assert recovery_page.evaluate('window.syntheticSaves.length') == 1
        recovery_page.close()
        custom = json_module.loads((root/'fixtures/agenda-heterogeneous.json').read_text(encoding='utf-8'))
        custom_page = browser.new_page(viewport={'width': 900, 'height': 700}, locale='pt-BR')
        custom_page.on('pageerror', lambda error: errors.append(str(error)))
        custom_page.add_init_script(recovery_init + ';window.syntheticConflict=false;window.syntheticCollector.settings.schedule=' + json_module.dumps(custom) + ';')
        custom_page.goto(url)
        custom_page.get_by_text('Horários por dia e turno — consultar agenda', exact=True).wait_for()
        custom_page.get_by_role('button', name='Editar agenda', exact=True).click()
        custom_page.get_by_role('button', name='Salvar', exact=True).click()
        custom_page.get_by_role('heading', name='Agenda de coleta').wait_for(state='hidden')
        assert custom_page.evaluate('window.syntheticSaves.length') == 0  # No-op must not write anything.
        custom_page.get_by_role('button', name='Editar agenda', exact=True).click()
        custom_page.get_by_label('Dia e turno', exact=True).click()
        custom_page.get_by_role('option', name='Segunda · Matutino', exact=True).click()
        type_time(custom_page, 1, '08', '15')
        try:
            expect(custom_page.get_by_role('button', name='Salvar', exact=True)).to_be_enabled()
        except AssertionError:
            raise AssertionError('Custom agenda blocked: ' + custom_page.get_by_role('dialog').inner_text()[-500:])
        custom_page.get_by_role('button', name='Salvar', exact=True).click()
        custom_page.get_by_role('heading', name='Agenda de coleta').wait_for(state='hidden')
        expected = json_module.loads(json_module.dumps(custom))
        expected['rules'][2]['times'][0] = '08:15'
        assert custom_page.evaluate('window.syntheticSaves') == [expected]
        custom_page.get_by_role('button', name='Editar agenda', exact=True).click()
        custom_page.get_by_label('Fuso horário', exact=True).fill('America/Invalid')
        expect(custom_page.get_by_role('button', name='Salvar', exact=True)).to_be_disabled()
        custom_page.get_by_label('Fuso horário', exact=True).fill('America/Manaus')
        expect(custom_page.get_by_role('button', name='Salvar', exact=True)).to_be_disabled()
        confirmation = custom_page.get_by_role('checkbox', name='Confirmo a alteração do fuso e dos horários de execução.')
        confirmation.focus(); confirmation.press('Space')
        expect(confirmation).to_be_checked()
        custom_page.get_by_role('button', name='Salvar', exact=True).click()
        custom_page.get_by_role('heading', name='Agenda de coleta').wait_for(state='hidden')
        expected['timezone'] = 'America/Manaus'
        assert custom_page.evaluate('window.syntheticSaves[1]') == expected
        custom_page.set_viewport_size({'width': 375, 'height': 720})
        custom_page.get_by_role('button', name='Editar agenda', exact=True).click()
        custom_page.get_by_label('Dia e turno', exact=True).click()
        custom_page.get_by_role('option', name='Segunda · Matutino', exact=True).click()
        rows = custom_page.locator('[data-time-row]')
        last_id = rows.nth(2).get_attribute('data-time-row')
        custom_page.get_by_role('button', name='Remover horário 1', exact=True).click()
        expect(rows).to_have_count(2)
        assert rows.nth(1).get_attribute('data-time-row') == last_id
        expect(rows.first.get_by_role('spinbutton').first).to_be_focused()
        assert custom_page.get_by_role('dialog').evaluate('el=>el.scrollWidth<=el.clientWidth+1')
        custom_page.screenshot(path=str(out/'schedule-lossless-mobile.png'), full_page=True, animations='disabled')
        custom_page.get_by_role('button', name='Cancelar', exact=True).click()
        assert custom_page.evaluate('window.syntheticSaves.length') == 2  # Cancelling removal does not write.
        custom_page.get_by_role('button', name='Editar agenda', exact=True).click()
        custom_page.get_by_label('Dia e turno', exact=True).click()
        custom_page.get_by_role('option', name='Segunda · Matutino', exact=True).click()
        recheck = custom_page.get_by_role('group', name='Conferência do turno (opcional)', exact=True).get_by_role('spinbutton')
        for segment in (recheck.nth(0), recheck.nth(1)):
            segment.press('Backspace'); segment.press('Backspace')
        expect(custom_page.get_by_role('button', name='Salvar', exact=True)).to_be_enabled()
        recheck.nth(0).click(); recheck.nth(0).press_sequentially('12')
        expect(custom_page.get_by_role('button', name='Salvar', exact=True)).to_be_disabled()
        custom_page.get_by_label('Dia e turno', exact=True).click()
        custom_page.get_by_role('option', name='Terça · Matutino', exact=True).click()
        expect(custom_page.get_by_role('button', name='Salvar', exact=True)).to_be_enabled()
        assert all(part.get_attribute('data-placeholder') == 'true' for part in recheck.all())
        custom_page.get_by_role('button', name='Cancelar', exact=True).click()
        assert custom_page.evaluate('window.syntheticSaves.length') == 2
        custom_page.close()
        assert not errors,errors
        print('Audit regressions passed: diagnostics identify separate cards; discarded native result stays hidden and blocks new reads until completion; desktop shell navigates its four pages; agenda conflict keeps the draft and saves once resolved.')
        print(json.dumps({'passed':True,'checks':['empty state','synthetic demo','pagination','student filter','dark theme','view return','clear preview','HTML import','invalid HTML fail-closed','repeat demo','mobile overflow','schedule presets','schedule validation','schedule save and reload','schedule undo and restore','schedule mobile overflow','fox visible','fox always shown','fox pet interaction','one atlas reused without frame fetches','fox reduced-motion','no browser exceptions'],'screenshots':str(out)},ensure_ascii=False))
        browser.close()
finally:
    server.shutdown(); server.server_close(); thread.join()
