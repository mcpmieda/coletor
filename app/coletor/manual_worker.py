"""External Edge worker without the desktop bridge. Private, transient IPC."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading

from .limits import MAX_HTML_BYTES, MAX_REQUEST_BYTES, MAX_NODES

# Clone only the documented report container; never serialize login inputs.
CAPTURE_JS = """() => {
  const password_form = !!document.querySelector('input[type="password"]');
  const containers = document.querySelectorAll('div.container-fluid');
  if (password_form || containers.length !== 1 || document.querySelectorAll('*').length > NODE_LIMIT) return {url: location.href, password_form, html: ''};
  const clone = containers[0].cloneNode(true);
  clone.querySelectorAll('script,style,form,input,textarea,select,button,iframe,object,embed,link,meta,video,audio,img').forEach(n => n.remove());
  for (const n of [clone, ...clone.querySelectorAll('*')]) {
    for (const a of [...n.attributes]) if (!['class','style','colspan','rowspan'].includes(a.name)) n.removeAttribute(a.name);
    if (n.hasAttribute('style')) {
      const pageBreak = n.style.pageBreakAfter;
      n.removeAttribute('style');
      if (pageBreak === 'always') n.setAttribute('style', 'page-break-after:always');
    }
  }
  const html = '<html><body>' + clone.outerHTML + '</body></html>';
  if (new TextEncoder().encode(html).length > HTML_LIMIT) return {error: 'report_too_large'};
  return {url: location.href, password_form, html};
}""".replace("NODE_LIMIT", str(MAX_NODES)).replace("HTML_LIMIT", str(MAX_HTML_BYTES))


def configure_context(context, request_delegate=None):
    from .manual_session import allowed_request
    def route_request(route):
        if not allowed_request(route.request.url):
            route.abort()
        elif request_delegate is not None:
            request_delegate(route)  # Python-only synthetic QA injection; never in the bridge.
        else:
            route.continue_()
    context.route("**/*", route_request)
    context.route_web_socket("**/*", lambda socket: socket.close())


def configure_page(page):
    page.on("popup", lambda popup: popup.close())
    page.on("download", lambda download: download.cancel())
    page.set_default_timeout(15000)
    page.set_default_navigation_timeout(30000)


class BrowserWorker:
    def __init__(self):
        self._process = None
        self._job = None
        self._temporary = None
        self._rpc_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self.cleanup = None
        self._closed = False

    def _command(self):
        executable = Path(sys.executable)
        # The portable GUI uses pythonw.exe, which has no usable stdio. The
        # private pipe worker must use its sibling python.exe, without a console.
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        return [str(executable), "-m", "coletor.manual_worker"]

    def _rpc(self, command, timeout=40):
        with self._rpc_lock:
            process = self._process
            if process is None or process.poll() is not None:
                raise RuntimeError("session_closed")
            process.stdin.write(json.dumps(command) + "\n")
            process.stdin.flush()
            messages = queue.Queue(maxsize=1)

            def read():
                try:
                    messages.put(process.stdout.readline(MAX_REQUEST_BYTES + 1))
                except (OSError, ValueError):
                    messages.put("")
            threading.Thread(target=read, daemon=True).start()
            try:
                line = messages.get(timeout=timeout)
            except queue.Empty:
                self.close()
                raise RuntimeError("session_timeout") from None
            if not line or len(line.encode("utf-8")) > MAX_REQUEST_BYTES or not line.endswith("\n"):
                self.close()
                raise RuntimeError("invalid_worker_response")
            body = json.loads(line)
            if not isinstance(body, dict) or "error" in body:
                raise RuntimeError("source_unavailable")
            return body

    def open(self, url):
        if sys.platform != "win32":
            raise RuntimeError("windows_required")
        from .process_scope import WindowsJob
        with self._close_lock:
            if self._closed:
                raise RuntimeError("session_closed")
            self._temporary = tempfile.TemporaryDirectory(prefix="coletor-session-")
            environment = os.environ.copy()
            environment.update(TMP=self._temporary.name, TEMP=self._temporary.name)
            # Do not inherit browser debug/trace settings, which could save secrets.
            for key in ("DEBUG", "PWDEBUG", "PLAYWRIGHT_BROWSERS_PATH", "NODE_OPTIONS"):
                environment.pop(key, None)
            self._job = WindowsJob()
            root = Path(__file__).resolve().parents[2]
            self._process = subprocess.Popen(self._command(), cwd=root,
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                             text=True, encoding="utf-8", env=environment,
                                             creationflags=subprocess.CREATE_NO_WINDOW)
            # Child waits on stdin: containment is established before any Edge/Node child.
            self._job.assign(self._process.pid)
        self._rpc({"command": "open", "url": url})

    def capture(self):
        return self._rpc({"command": "capture"})

    def close(self):
        with self._close_lock:
            self._closed = True
            process, self._process = self._process, None
            if process is not None:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
            if self._job is not None:
                try:
                    self.cleanup = self._job.finish(grace=1)
                finally:
                    self._job.close()
                    self._job = None
            if process is not None:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                process.stdout.close()
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None


def main():
    # Windows redirected stdio otherwise uses the system code page. JSON carries
    # Portuguese text and symbols, so both ends of private IPC use explicit UTF-8.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    from .manual_session import matches_source
    from urllib.parse import parse_qsl, urlsplit
    from playwright.sync_api import sync_playwright
    initial = json.loads(sys.stdin.readline(2048))
    url = initial.get("url", "")
    params = dict(parse_qsl(urlsplit(url).query))
    if initial.get("command") != "open" or not matches_source(url, params.get("ct"), params.get("ano")):
        raise ValueError("invalid_scope")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=False, chromium_sandbox=True)
        try:
            context = browser.new_context(accept_downloads=False, service_workers="block")
            configure_context(context)
            page = context.new_page()
            configure_page(page)
            # Navigation errors can mean an unapproved SSO origin. Do not broaden access.
            try:
                page.goto(url, wait_until="domcontentloaded")
            except Exception:
                pass
            print(json.dumps({"opened": True}), flush=True)
            for line in sys.stdin:
                command = json.loads(line)
                if command.get("command") != "capture":
                    break
                try:
                    before = page.url
                    if not matches_source(before, params["ct"], params["ano"]):
                        payload = {"url": "", "password_form": False, "html": ""}
                    else:
                        payload = page.evaluate(CAPTURE_JS)
                        if page.url != before or payload.get("url") != before:
                            payload = {"error": "page_changed"}
                        elif len(payload.get("html", "").encode("utf-8")) > MAX_HTML_BYTES:
                            payload = {"error": "report_too_large"}
                    encoded = json.dumps(payload, ensure_ascii=False)
                    if len(encoded.encode("utf-8")) > MAX_REQUEST_BYTES:
                        encoded = '{"error":"transport_limit"}'
                    print(encoded, flush=True)
                except Exception:
                    print('{"error":"source_unavailable"}', flush=True)
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print('{"error":"session_unavailable"}', flush=True)
