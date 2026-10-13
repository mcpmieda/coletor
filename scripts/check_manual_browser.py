"""Private Windows Edge QA: every request is synthetic or aborted, no login."""
import argparse
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
          "ephemeral_context_closed", "owned_processes_stopped"]


def worker(output):
    if sys.stdin.readline().strip() != "RUN":
        return
    from coletor.demo import build_fixture
    from coletor.manual_session import captured_preview, source_url
    from coletor.manual_worker import CAPTURE_JS, configure_context, configure_page
    from playwright.sync_api import sync_playwright
    raw = re.sub(r' data-(?:report|class-id|year|student-count|student-row|report-end)="[^"]*"', '',
                 build_fixture(include_edge_cases=False))
    raw = raw.replace('</body>', '<form><input value="SYNTHETIC_PASSWORD_DO_NOT_KEEP"></form><script>window.syntheticOnly=true</script></body>')
    url = source_url("13331", 2026)
    served = []
    checks = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=False, chromium_sandbox=True)
        try:
            context = browser.new_context(accept_downloads=False, service_workers="block")
            def fixture(route):
                served.append(route.request.url)
                route.fulfill(status=200, content_type="text/html", body=raw)
            configure_context(context, fixture)
            page = context.new_page()
            configure_page(page)
            page.goto(url)
            checks["external_edge"] = True
            checks["no_privileged_bridge"] = page.evaluate("!window.pywebview && !window.chrome?.webview")
            payload = page.evaluate(CAPTURE_JS)
            checks["exact_scope"] = payload["url"] == url
            checks["credentials_removed"] = "SYNTHETIC_PASSWORD_DO_NOT_KEEP" not in json.dumps(payload) and '<script' not in payload['html']
            result = captured_preview(payload, "13331", 2026)
            checks["manual_preview_blocked"] = not result["validation"]["allowed"] and not result["capture"]["identity_verified"]
            page.evaluate("document.body.insertAdjacentHTML('beforeend','<input type=password value=SYNTHETIC_PASSWORD_DO_NOT_KEEP>')")
            login = page.evaluate(CAPTURE_JS)
            checks["password_form_rejected"] = login["password_form"] and login["html"] == '' and 'SYNTHETIC_PASSWORD_DO_NOT_KEEP' not in json.dumps(login)
            outside = page.evaluate("fetch('https://unapproved.invalid/blocked').then(()=>false,()=>true)")
            checks["outside_origin_blocked"] = outside and served == [url]
            page.evaluate("window.open('https://unapproved.invalid/popup')")
            page.wait_for_timeout(300)
            checks["popup_closed"] = len(context.pages) == 1
            context.close()
            fresh = browser.new_context(accept_downloads=False, service_workers="block")
            checks["ephemeral_context_closed"] = len(browser.contexts) == 1 and fresh.cookies() == []
            fresh.close()
        finally:
            browser.close()
    Path(output).write_text(json.dumps({"checks": checks}), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        worker(args.output)
        return
    from check_windows_portable import WindowsJob
    args.output.parent.mkdir(parents=True, exist_ok=True)
    job = WindowsJob()
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
            checks = json.loads(evidence.read_text(encoding='utf-8'))['checks'] if evidence.exists() else {}
            cleanup = job.finish()
            checks['owned_processes_stopped'] = cleanup['verified']
            report = {'status': 'passed' if process.returncode == 0 and all(checks.get(k) is True for k in CHECKS) else 'failed',
                      'checks': checks, 'cleanup': cleanup, 'real_network': False, 'real_credentials': False}
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
