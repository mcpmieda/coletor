"""Private Windows Edge QA: every request is synthetic or aborted, no login."""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ["external_edge", "no_privileged_bridge", "exact_scope", "password_form_rejected",
          "credentials_removed", "outside_origin_blocked", "popup_closed", "manual_preview_blocked",
          "ephemeral_context_closed", "owned_processes_stopped", "get_redirect_destination_uncontacted",
          "post307_destination_uncontacted", "post308_destination_uncontacted", "authorized_redirect_preserved", "http2_disabled", "proxy_self_test", "webrtc_disabled"]


async def exercise_browser(output):
    from coletor.demo import build_fixture
    from coletor.manual_session import captured_preview, source_url
    from coletor.manual_worker import CAPTURE_JS, configure_context, configure_page, browser_options
    from coletor.origin_proxy import OriginProxy, verify_proxy
    from playwright.async_api import async_playwright
    spec = importlib.util.spec_from_file_location('qa_https', Path(__file__).with_name('qa_https.py'))
    qa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qa)
    raw = re.sub(r' data-(?:report|class-id|year|student-count|student-row|report-end)="[^"]*"', '',
                 build_fixture(include_edge_cases=False))
    # All markers are INSIDE the captured report container, including dynamic
    # fields. This fails if serialization merely excludes outside elements.
    attack = """<form data-secret="QA_ATTRIBUTE_SECRET"><input value="QA_FIELD_SECRET"></form>
    <textarea>QA_TEXTAREA_SECRET</textarea><input type=hidden value="QA_HIDDEN_SECRET">
    <script>window.qaScript='QA_SCRIPT_SECRET';setTimeout(()=>document.querySelector('.container-fluid').insertAdjacentHTML('beforeend','<input class=qa-dynamic-field value=QA_DYNAMIC_SECRET>'),50)</script>
    <span data-secret="QA_ATTRIBUTE_SECRET" onclick="QA_EVENT_SECRET()" style="background:url(QA_STYLE_SECRET)"></span>"""
    raw = raw.replace('<div class="container-fluid">', '<div class="container-fluid">' + attack, 1)
    url = source_url("13331", 2026)
    checks = {}
    with qa.SyntheticHttps(raw) as source, OriginProxy(dial=source.dial) as proxy:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**browser_options(proxy))
            try:
                # QA ONLY: local self-signed TLS fixture; production never disables TLS validation.
                context = await browser.new_context(accept_downloads=False, service_workers="block", ignore_https_errors=True)
                page = await context.new_page()
                await verify_proxy(page, proxy)
                checks["proxy_self_test"] = True
                await configure_context(context)
                configure_page(page)
                await page.goto(url)
                await page.locator('.qa-dynamic-field').wait_for(state='attached')
                await page.evaluate("""for (const small of document.querySelectorAll('.ls-box1 small')) {
                  const fields=small.querySelectorAll('strong');
                  fields[1].textContent='QA_BIRTH_SECRET';fields[2].textContent='QA_PARENT_SECRET';fields[4].textContent='QA_ENROLLMENT_SECRET';
                }""")
                checks["external_edge"] = True
                checks["webrtc_disabled"] = await page.evaluate("typeof RTCPeerConnection === 'undefined'")
                checks["no_privileged_bridge"] = await page.evaluate("!window.pywebview && !window.chrome?.webview")
                payload = await page.evaluate(CAPTURE_JS)
                checks["exact_scope"] = payload["url"] == url
                markers = ['QA_ATTRIBUTE_SECRET', 'QA_FIELD_SECRET', 'QA_TEXTAREA_SECRET', 'QA_HIDDEN_SECRET',
                           'QA_SCRIPT_SECRET', 'QA_DYNAMIC_SECRET', 'QA_EVENT_SECRET', 'QA_STYLE_SECRET',
                           'QA_BIRTH_SECRET', 'QA_PARENT_SECRET', 'QA_ENROLLMENT_SECRET']
                checks["credentials_removed"] = all(marker not in json.dumps(payload) for marker in markers) and '<script' not in payload['html']
                result = captured_preview(payload, "13331", 2026)
                checks["manual_preview_blocked"] = not result["validation"]["allowed"] and not result["capture"]["identity_verified"]
                await page.evaluate("document.querySelector('.container-fluid').insertAdjacentHTML('beforeend','<input type=password value=QA_PASSWORD_SECRET>')")
                login = await page.evaluate(CAPTURE_JS)
                checks["password_form_rejected"] = login["password_form"] and login["html"] == '' and 'QA_PASSWORD_SECRET' not in json.dumps(login)
                outside = await page.evaluate("fetch('https://unapproved.invalid/blocked').then(()=>false,()=>true)")
                checks["outside_origin_blocked"] = outside and source.contacts == 0
                await page.evaluate("window.open('https://unapproved.invalid/popup')")
                await asyncio.sleep(0.3)
                checks["popup_closed"] = len(context.pages) == 1
                for path, method, name in [('/qa-redirect-get', 'GET', 'get_redirect_destination_uncontacted'),
                                           ('/qa-post307', 'POST', 'post307_destination_uncontacted'),
                                           ('/qa-post308', 'POST', 'post308_destination_uncontacted')]:
                    denied_before = proxy.denied_connections
                    failed = await page.evaluate("""async ([path, method]) => {
                        try { await fetch(path, {method, ...(method==='POST' ? {body:'SYNTHETIC_CREDENTIAL_FIXTURE_ONLY'} : {})}); return false; }
                        catch { return true; }
                    }""", [path, method])
                    checks[name] = failed and source.contacts == 0 and proxy.denied_connections > denied_before
                checks['authorized_redirect_preserved'] = await page.evaluate("fetch('/qa-allowed-redirect').then(r=>r.text()).then(t=>t==='synthetic redirect arrived')")
                checks['post307_destination_uncontacted'] &= source.post_checks == [True, True]
                checks['post308_destination_uncontacted'] &= source.post_checks == [True, True]
                checks['http2_disabled'] = bool(source.alpns) and 'h2' not in source.alpns
                synthetic_cookie_exists = any(cookie['name'] == 'coletor_synthetic_qa' for cookie in await context.cookies())
                await context.close()
                fresh = await browser.new_context(accept_downloads=False, service_workers="block")
                checks["ephemeral_context_closed"] = synthetic_cookie_exists and len(browser.contexts) == 1 and await fresh.cookies() == []
                await fresh.close()
            finally:
                await browser.close()
    Path(output).write_text(json.dumps({"checks": checks, 'denied_destination_contacts': source.contacts}), encoding="utf-8")


def worker(output):
    if sys.stdin.readline().strip() != "RUN":
        return
    asyncio.run(exercise_browser(output))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        worker(args.output)
        return
    spec = importlib.util.spec_from_file_location('portable_smoke', Path(__file__).with_name('check_windows_portable.py'))
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    job = smoke.WindowsJob()
    with tempfile.TemporaryDirectory(prefix='manual-browser-qa-') as directory:
        evidence = Path(directory) / 'result.json'
        env = os.environ.copy()
        env.update(TMP=directory, TEMP=directory)
        process = subprocess.Popen([str(args.python), '-I', str(Path(__file__).resolve()), '--worker', '--output', str(evidence)],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   text=True, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            job.assign(process.pid)
            process.communicate('RUN\n', timeout=90)
            worker_report = json.loads(evidence.read_text(encoding='utf-8')) if evidence.exists() else {}
            checks = worker_report.get('checks', {})
            cleanup = job.finish()
            checks['owned_processes_stopped'] = cleanup['verified']
            report = {'status': 'passed' if process.returncode == 0 and all(checks.get(k) is True for k in CHECKS) else 'failed',
                      'checks': checks, 'cleanup': cleanup, 'real_network': False, 'real_credentials': False,
                      'denied_destination_contacts': worker_report.get('denied_destination_contacts'),
                      'denied_destination_body_bytes': 0 if worker_report.get('denied_destination_contacts') == 0 else None}
            args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            if report['status'] != 'passed':
                raise SystemExit('manual_browser_qa_failed')
        finally:
            job.close()
            if process.poll() is None:
                process.kill()
                process.wait(5)


if __name__ == '__main__':
    main()
