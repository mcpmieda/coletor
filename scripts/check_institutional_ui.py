"""Rendered UI regression with a clearly synthetic bridge, never a login proof.

Browser plugin initialization fails in this environment. Regular Playwright is
used only against the local compiled app; no Microsoft/Smecel page is contacted.
Native Python denial is verified separately by test_desktop_access.py.
"""
import json
import os
from pathlib import Path
import threading
from playwright.sync_api import expect, sync_playwright
from coletor.server import PreviewServer

server = PreviewServer(0)
threading.Thread(target=server.serve_forever, daemon=True).start()
out = Path(os.environ.get("QA_OUTPUT", "artifacts/institutional-ui"))
out.mkdir(parents=True, exist_ok=True)
errors = []
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH", p.chromium.executable_path), headless=True)
        page = browser.new_page(viewport={"width": 1240, "height": 900}, locale="pt-BR", reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("""window.__fixture={authorized:false,statusCalls:0,settingsCalls:0,logoutCalls:0,loginCalls:0,loginErrorCode:null,defer:false,pending:[]};
          window.pywebview={api:{
            get_institutional_access_status:async()=>{const f=window.__fixture;f.statusCalls++;
              if(f.defer) return new Promise(resolve=>f.pending.push(resolve));
              return {authenticated:f.authorized,authorized:f.authorized,pairingCode:f.pairingCode,code:f.code};},
            open_institutional_login:async()=>{const f=window.__fixture;f.loginCalls++;
              return f.loginErrorCode?{error:'Autorização não disponível.',code:f.loginErrorCode}:{ok:true};},
            logout_institutional_access:async()=>{window.__fixture.logoutCalls++;window.__fixture.authorized=false;return {ok:true};},
            get_local_recovery_status:async()=>({pending:false,count:0,oldest:null,newest:null,unreadable:false}),
            discard_local_pending_collection:async()=>({ok:true,discarded:false}),
            get_local_settings:async()=>{window.__fixture.settingsCalls++;return {settings:{schemaVersion:1,schedule:null,theme:'system',fox:{version:1,show:true,animate:true}}};},
            get_desktop_status:async()=>({version:1,sourceState:'idle',canHide:true}),
            set_tray_context:async()=>({ok:true}),
            get_manual_class_selection_preferences:async()=>({version:1,classes:[]}),
            get_manual_session_status:async()=>({state:'closed'})}};
        """)
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/#coletor-desktop")
        expect(page.get_by_role("heading", name="Entrar no Ecossistema")).to_be_visible()
        expect(page.get_by_role("button", name="Usar dados de exemplo")).to_have_count(0)
        assert page.evaluate("window.__fixture.settingsCalls") == 0
        assert page.locator('input[type=password]').count() == 0
        # The exact production loop: native "Sim" fails, then automatic
        # authorization polling wrongly replaces the failure with the default.
        for code in ('DEVICE_KEY_UNAVAILABLE', 'ACCESS_UNAVAILABLE', 'PAIRING_PENDING'):
            page.evaluate("(code) => window.__fixture.loginErrorCode=code", code)
            page.get_by_role('button', name='Entrar no Ecossistema').click()
            expect(page.get_by_text('Código: ' + code + '.', exact=False)).to_be_visible()
            page.evaluate("window.dispatchEvent(new Event('coletoraccesschanged'));window.dispatchEvent(new Event('focus'))")
            expect(page.get_by_text('Código: ' + code + '.', exact=False)).to_be_visible()
        assert page.evaluate("window.__fixture.loginCalls") == 3
        page.evaluate("window.__fixture.loginErrorCode=null")
        page.get_by_role('button', name='Entrar no Ecossistema').click()
        expect(page.get_by_text('Pedido preparado. Confira o navegador', exact=False)).to_be_visible()
        page.screenshot(path=str(out / "blocked.png"), full_page=True)
        page.evaluate("window.__fixture.pairingCode='123456';window.dispatchEvent(new Event('coletoraccesschanged'))")
        expect(page.get_by_text('123456', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='Cancelar autorização')).to_be_visible()
        page.screenshot(path=str(out / 'pairing.png'), full_page=True)
        page.evaluate("window.__fixture.pairingCode='';window.__fixture.code='SERVER_REVOCATION_PENDING';window.dispatchEvent(new Event('coletoraccesschanged'))")
        expect(page.get_by_role('button', name='Concluir saída')).to_be_visible()
        page.screenshot(path=str(out / 'revocation-pending.png'), full_page=True)
        page.evaluate("window.__fixture.code=undefined")
        page.evaluate("window.__fixture.authorized=true;window.dispatchEvent(new Event('coletoraccesschanged'))")
        expect(page.get_by_role("heading", name="Coleta da frequência")).to_be_visible()
        assert page.evaluate("window.__fixture.settingsCalls") > 0
        settings_calls = page.evaluate("window.__fixture.settingsCalls")
        status_calls = page.evaluate("window.__fixture.statusCalls")
        page.evaluate("window.dispatchEvent(new Event('coletoraccesschanged'))")
        page.wait_for_function("before => window.__fixture.statusCalls >= before + 2", arg=status_calls)
        assert page.evaluate("window.__fixture.settingsCalls") == settings_calls, "Authorization polling must not reload preferences"
        page.screenshot(path=str(out / "synthetic-authorized.png"), full_page=True)
        page.evaluate("window.__fixture.defer=true;window.dispatchEvent(new Event('coletoraccesschanged'))")
        page.wait_for_function("window.__fixture.pending.length>0")
        page.get_by_role("button", name="Sair da conta").click()
        expect(page.get_by_role("heading", name="Entrar no Ecossistema")).to_be_visible()
        page.evaluate("window.__fixture.pending.splice(0).forEach(resolve=>resolve({authenticated:true,authorized:true}))")
        expect(page.get_by_role("button", name="Usar dados de exemplo")).to_have_count(0)
        assert page.evaluate("window.__fixture.logoutCalls") == 1
        assert not errors, errors
        (out / "results.json").write_text(json.dumps({"passed": True, "synthetic_bridge_only": True,
            "native_authorization_proven": False, "checks": ["denied-before-settings", "login-without-password-field",
            "login-errors-survive-status-poll", "pairing-code-and-cancellation", "offline-revocation-completion", "authorized-ui", "permission-poll-preserves-preferences", "logout-discards-late-authorization"], "page_errors": 0}, indent=2), encoding="utf-8")
        browser.close()
finally:
    server.shutdown()
    server.server_close()
