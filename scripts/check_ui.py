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
        page.get_by_role('heading', name='Primeiro, conferir. Depois, sincronizar.').wait_for()
        fox = page.get_by_role('img', name='Raposa vermelha, mascote do coletor')
        fox.wait_for()
        expect(fox).to_have_js_property('complete', True)
        assert fox.evaluate('img => img.complete && img.naturalWidth > 0'), 'Missing fox sprite'
        assert page.locator('.fox-stage').get_attribute('data-motion') == 'off'
        assert page.locator('.fox-button').evaluate('el => getComputedStyle(el).animationName') == 'none'
        page.get_by_role('checkbox', name='Mostrar raposa', exact=True).uncheck()
        assert fox.count() == 0
        page.reload()
        assert page.get_by_role('img', name='Raposa vermelha, mascote do coletor').count() == 0
        page.get_by_role('checkbox', name='Mostrar raposa', exact=True).check()
        page.emulate_media(reduced_motion='no-preference')
        page.locator('.fox-stage[data-motion=on]').wait_for()
        expect(fox).to_have_js_property('complete', True)
        atlas_count = len(atlas_requests)
        page.get_by_role('button',name='Fazer carinho na raposa').click()
        assert page.locator('.fox-stage').get_attribute('data-action') == 'pet'
        expect(page.locator('.fox-stage')).to_have_attribute('data-pose', 'happy')
        assert len(atlas_requests) == atlas_count, 'Sprite animation fetched another image'
        page.get_by_role('checkbox',name='Animar mascote',exact=True).uncheck()
        assert page.locator('.fox-stage').get_attribute('data-motion') == 'off'
        page.get_by_role('checkbox',name='Animar mascote',exact=True).check()
        page.emulate_media(reduced_motion='reduce')
        page.locator('.fox-stage[data-motion=off]').wait_for()
        assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()") == '#a32743'
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'empty-light.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='Carregar demonstração').click()
        page.get_by_role('heading', name='Prévia da turma').wait_for()
        assert page.get_by_text('Aluno sintético 001',exact=True).count() > 0
        assert page.get_by_text('Envio indisponível neste protótipo').is_visible()
        assert page.locator('tbody tr').count() == 24
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
        page.get_by_role('button', name='Aparência').click()
        page.get_by_role('option', name='Escura', exact=True).click()
        page.get_by_role('listbox').wait_for(state='hidden')
        assert page.locator('html').get_attribute('data-theme') == 'dark'
        assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()") == '#f28ba0'
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'demo-dark.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='Próximas etapas', exact=True).click()
        page.get_by_role('heading', name='Da prévia ao envio seguro').wait_for()
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'roadmap-dark.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='Prévia e validação', exact=True).click()
        page.get_by_role('heading', name='Prévia da turma').wait_for()
        page.get_by_role('button', name='Limpar prévia').click()
        page.get_by_role('heading', name='Primeiro, conferir. Depois, sincronizar.').wait_for()
        page.get_by_label('Selecionar diário HTML').set_input_files(str(root/'fixtures/annual-synthetic.html'))
        page.get_by_role('heading', name='Prévia da turma').wait_for()
        assert page.get_by_text('Prévia de arquivo local', exact=False).count() == 1
        page.get_by_role('button', name='Limpar prévia').click()
        page.get_by_label('Selecionar diário HTML').set_input_files({'name':'invalid.html','mimeType':'text/html','buffer':b'<html><form>login</form></html>'})
        page.get_by_role('heading', name='Prévia da turma').wait_for()
        assert page.get_by_text('Envio indisponível neste protótipo').is_visible()
        # School schedule remains a local preview: edit, validate, save, reload, undo.
        page.get_by_role('button', name='Agenda de coleta', exact=True).click()
        page.get_by_role('heading', name='Horários de coleta').wait_for()
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'schedule-initial.png'), full_page=True, animations='disabled')
        assert page.get_by_label('Fuso da escola').input_value() == 'America/Bahia'
        assert page.get_by_label('Coletas Sexta-feira Matutino', exact=True).input_value().startswith('08:40')
        assert not page.get_by_role('checkbox', name='Incluir Sábado Matutino').is_checked()
        monday = page.get_by_label('Coletas Segunda-feira Matutino', exact=True)
        monday.fill('24:00')
        page.get_by_role('button', name='Salvar prévia local', exact=True).click()
        assert page.get_by_role('alert').is_visible()
        monday.fill('08:15, 09:00, 09:55, 11:05, 11:55')
        page.get_by_role('button', name='Salvar prévia local', exact=True).click()
        assert page.get_by_role('status').filter(has_text='Prévia salva').is_visible()
        page.reload()
        page.get_by_role('button', name='Agenda de coleta', exact=True).click()
        monday = page.get_by_label('Coletas Segunda-feira Matutino', exact=True)
        assert monday.input_value().startswith('08:15')
        monday.fill('08:30')
        page.get_by_role('button', name='Próximas etapas', exact=True).click()
        page.get_by_role('button', name='Agenda de coleta', exact=True).click()
        assert monday.input_value() == '08:30', 'Draft lost on navigation'
        page.get_by_role('button', name='Descartar alterações', exact=True).click()
        assert monday.input_value().startswith('08:15')
        page.get_by_role('button', name='Vespertino', exact=True).click()
        assert page.get_by_label('Rechecagem Sexta-feira Vespertino', exact=True).input_value() == '18:30'
        page.get_by_role('button', name='Restaurar padrão', exact=True).click()
        page.get_by_role('button', name='Salvar prévia local', exact=True).click()
        page.get_by_role('button', name='Matutino', exact=True).click()
        assert monday.input_value().startswith('08:05')
        page.set_viewport_size({'width':1240,'height':820})
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'schedule-dark.png'), full_page=True, animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Schedule desktop overflow'
        page.get_by_role('button', name='Aparência').click()
        page.get_by_role('option', name='Clara', exact=True).click()
        page.get_by_role('listbox').wait_for(state='hidden')
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'schedule-light.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='Próximas etapas', exact=True).click()
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'roadmap-light.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='Agenda de coleta', exact=True).click()
        page.set_viewport_size({'width':390,'height':844})
        page.mouse.move(0, 0)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(out/'schedule-mobile.png'), full_page=True, animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Schedule mobile overflow'
        page.get_by_role('button', name='Prévia e validação', exact=True).click()
        # Repeated load after error and clearing; no stale preview.
        page.get_by_role('button', name='Carregar demonstração').click()
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
        assert page.get_by_role('button',name='Abrir HTML').is_visible()
        assert not errors, errors
        print(json.dumps({'passed':True,'checks':['empty state','synthetic demo','pagination','student filter','dark theme','roadmap return','clear preview','HTML import','invalid HTML fail-closed','repeat demo','mobile overflow','schedule presets','schedule validation','schedule save and reload','schedule undo and restore','schedule mobile overflow','fox visible','fox preference persists','fox pet interaction','one atlas reused without frame fetches','fox reduced-motion','fox animation toggle','roadmap screenshots in both themes','no browser exceptions'],'screenshots':str(out)},ensure_ascii=False))
        browser.close()
finally:
    server.shutdown(); server.server_close(); thread.join()
