"""External Edge worker without the desktop bridge. Private, transient IPC."""
import asyncio
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

from .limits import MAX_HTML_BYTES, MAX_REQUEST_BYTES, MAX_NODES
from .origin_proxy import OriginProxy, verify_proxy

# Clone only the documented report container; never serialize login inputs.
CAPTURE_JS = """() => {
  const password_form = !!document.querySelector('input[type="password"]');
  const containers = document.querySelectorAll('div.container-fluid');
  if (password_form || containers.length !== 1 || document.querySelectorAll('*').length > NODE_LIMIT) return {url: location.href, password_form, html: ''};
  const clone = containers[0].cloneNode(true);
  for (const small of clone.querySelectorAll('.ls-box1 small')) {
    const fields = small.querySelectorAll('strong');
    if (fields.length === 5) for (const index of [1, 2, 4]) fields[index].textContent = '[não capturado]';
  }
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


# Observed public form of https://www.smecel.com.br/index.php: e-mail #usuario,
# password #senha and submit button[name=logar]. No CAPTCHA is solved or bypassed.
LOGIN_URL = "https://www.smecel.com.br/index.php"
LOGIN_FIELDS = ("#usuario", "#senha", 'button[type="submit"][name="logar"]')


async def sign_in(page, email, password):
    """Fill the Smecel form inside the isolated Edge only. The credential stays
    in this private worker; it is never logged, echoed or written to disk."""
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    if await page.locator('input[type="password"]').count() == 0:
        return {"logged_in": True}
    user, secret, submit = LOGIN_FIELDS
    await page.fill(user, email)
    await page.fill(secret, password)
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
        await page.click(submit)
    return {"logged_in": await page.locator('input[type="password"]').count() == 0}


def browser_options(proxy):
    return {"channel": "msedge", "headless": False, "chromium_sandbox": True,
            "proxy": proxy.configuration,
            # HTTP/1.1 tunnels cannot coalesce an approved TLS connection across
            # origins; QUIC and non-proxied WebRTC UDP must not bypass the gate.
            "args": ["--disable-http2", "--disable-quic",
                     "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]}


def worker_environment(temporary):
    # Do not pass shell/cloud tokens, custom Node executables or debug settings
    # into the source browser. Only OS discovery and our own module path remain.
    keys = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "LOCALAPPDATA", "APPDATA",
            "USERPROFILE", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "SYSTEMDRIVE",
            "HOMEDRIVE", "HOMEPATH", "USERNAME", "USERDOMAIN", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in keys}
    environment.update(TMP=temporary, TEMP=temporary, PYTHONNOUSERSITE="1",
                       PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    return environment


async def configure_context(context, request_delegate=None):
    from .manual_session import allowed_request
    async def route_request(route):
        if not allowed_request(route.request.url):
            await route.abort()
        elif request_delegate is not None:
            await request_delegate(route)  # Python-only synthetic QA injection.
        else:
            await route.continue_()
    async def block_socket(socket):
        await socket.close()
    await context.route("**/*", route_request)
    await context.route_web_socket("**/*", block_socket)
    await context.add_init_script("""for (const name of ['RTCPeerConnection', 'webkitRTCPeerConnection']) {
      Object.defineProperty(globalThis, name, {configurable: false, get: () => undefined});
    }""")


def configure_page(page):
    async def close_popup(popup):
        try:
            await popup.close()
        except Exception:
            pass
    async def close_other_page(other):
        if other is not page:
            await close_popup(other)
    async def cancel_download(download):
        await download.cancel()
    page.on("popup", close_popup)
    # The popup event can wait for its initial navigation. Close at the context
    # page event too, including an aborted first navigation that stays blank.
    page.context.on("page", close_other_page)
    page.on("download", cancel_download)
    page.set_default_timeout(15000)
    page.set_default_navigation_timeout(30000)


class BrowserWorker:
    def __init__(self, storage_state=None):
        self._storage_state = storage_state
        self._process = None
        self._job = None
        self._temporary = None
        self._rpc_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self.cleanup = None
        self._closed = False
        self._cleanup_errors = []

    def _command(self):
        executable = Path(sys.executable)
        # The portable GUI uses pythonw.exe, which has no usable stdio. The
        # private pipe worker must use its sibling python.exe, without a console.
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        return [str(executable), "-B", "-m", "coletor.manual_worker"]

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
            environment = worker_environment(self._temporary.name)
            self._job = WindowsJob()
            root = Path(__file__).resolve().parents[2]
            self._process = subprocess.Popen(self._command(), cwd=root,
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                             text=True, encoding="utf-8", env=environment,
                                             creationflags=subprocess.CREATE_NO_WINDOW)
            # Child waits on stdin: containment is established before any Edge/Node child.
            self._job.assign(self._process.pid)
        initial = {"command": "open", "url": url}
        if self._storage_state is not None: initial['storage_state'] = self._storage_state
        self._rpc(initial)
        self._storage_state = None

    def discover(self, year):
        return self._rpc({"command": "list", "year": year})

    def capture_selected(self, class_id, year, context_key):
        return self._rpc({"command": "capture", "class_id": class_id, "year": year, "context_key": context_key})

    def capture(self):
        return self._rpc({"command": "capture"})

    def login(self, email, password):
        # Same private pipe as captures; the reply carries only a boolean.
        return self._rpc({"command": "login", "email": email, "password": password}, timeout=60).get("logged_in") is True

    def export_state(self):
        # This private pipe is never the privileged webview bridge.
        return self._rpc({"command": "state"})['storage_state']

    def close(self):
        with self._close_lock:
            self._closed = True
            self._storage_state = None
            process, self._process = self._process, None
            if process is not None:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
                # EOF cancels the in-flight browser task. Let the SDK close
                # Edge and its mapped metrics/artifact files before using the
                # Job Object fallback; killing it mid-close caused WinError 32.
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
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
                for attempt in range(9):
                    try:
                        self._temporary.cleanup()
                        break
                    except OSError as error:
                        self._cleanup_errors.append(getattr(error, "winerror", None))
                        self._temp_failed_path = getattr(error, "filename", None)
                        # Windows can briefly return ERROR_ACCESS_DENIED (5)
                        # as well as ERROR_SHARING_VIOLATION (32) while Edge's
                        # closed process tree releases file-system handles.
                        # Retry 5 only AFTER the owned Windows Job confirmed
                        # zero surviving processes; do not change permissions,
                        # bypass ACLs, remove outside paths or suppress errors.
                        code = getattr(error, "winerror", None)
                        finished = bool(self.cleanup and self.cleanup.get("verified"))
                        if (code != 32 and not (code == 5 and finished)) or attempt == 8:
                            raise
                        time.sleep(0.05 * 2 ** attempt)
                self._temporary = None


async def browser_session(initial):
    from .manual_session import matches_source, source_url
    from .class_catalog import list_url, matches_list, catalog_from_observation, CATALOG_JS
    from urllib.parse import parse_qsl, urlsplit
    from playwright.async_api import async_playwright
    url = initial.get("url", "")
    params = dict(parse_qsl(urlsplit(url).query))
    listing_mode = matches_list(url, params.get("ano"))
    if initial.get("command") != "open" or not (listing_mode or matches_source(url, params.get("ct"), params.get("ano"))):
        raise ValueError("invalid_scope")
    with OriginProxy() as proxy:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**browser_options(proxy))
            try:
                context = await browser.new_context(accept_downloads=False, service_workers="block",
                                                    storage_state=initial.get('storage_state'))
                page = await context.new_page()
                configure_page(page)
                await verify_proxy(page, proxy)
                await configure_context(context)
                try:
                    await page.goto(url, wait_until="domcontentloaded")
                except Exception:
                    pass
                print(json.dumps({"opened": True}), flush=True)
                async def read_catalog(year):
                    await page.goto(list_url(year), wait_until="domcontentloaded")
                    before = page.url
                    observation = await page.evaluate(CATALOG_JS)
                    if page.url != before or observation.get("url") != before:
                        raise ValueError("listing_changed")
                    return catalog_from_observation(observation, year)

                async def capture_reply(command):
                    try:
                        if command['command'] == 'state':
                            state = await context.storage_state()
                            state = {'cookies': [c for c in state['cookies'] if c['domain'] in {'www.smecel.com.br', '.smecel.com.br', 'smecel.com.br'}],
                                     'origins': [o for o in state['origins'] if o['origin'] == 'https://www.smecel.com.br']}
                            encoded = json.dumps({'storage_state': state}, ensure_ascii=False)
                            if len(encoded.encode('utf-8')) > 1024 * 1024: raise ValueError('state_limit')
                            print(encoded, flush=True)
                            return
                        if command["command"] == "login":
                            payload = await sign_in(page, str(command.get("email", "")), str(command.get("password", "")))
                            print(json.dumps(payload), flush=True)
                            return
                        if command["command"] == "list":
                            payload = await read_catalog(command["year"])
                            print(json.dumps(payload, ensure_ascii=False), flush=True)
                            return
                        class_id, year = params.get("ct"), params.get("ano")
                        if listing_mode:
                            class_id, year = command.get("class_id"), command.get("year")
                            catalog = await read_catalog(year)
                            if (catalog["scope"]["context_key"] != command.get("context_key")
                                    or class_id not in {c["class_id"] for c in catalog["classes"]}):
                                raise ValueError("selected_class_unavailable")
                            await page.goto(source_url(class_id, year), wait_until="domcontentloaded")
                        before = page.url
                        if not matches_source(before, class_id, year):
                            payload = {"url": "", "password_form": False, "html": ""}
                        else:
                            payload = await page.evaluate(CAPTURE_JS)
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
                reader = asyncio.create_task(asyncio.to_thread(sys.stdin.readline, 2048))
                capture = None
                try:
                    while True:
                        pending = {reader} | ({capture} if capture is not None else set())
                        ready, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                        if capture is not None and capture in ready:
                            await capture
                            capture = None
                        if reader in ready:
                            line = reader.result()
                            if not line:
                                break
                            command = json.loads(line)
                            if command.get("command") not in {"capture", "list", "state", "login"}:
                                break
                            if capture is not None:
                                raise RuntimeError("overlapping_capture")
                            capture = asyncio.create_task(capture_reply(command))
                            # Continue listening while capture runs: EOF must
                            # interrupt it immediately, rather than wait for it.
                            reader = asyncio.create_task(asyncio.to_thread(sys.stdin.readline, 2048))
                finally:
                    if capture is not None:
                        capture.cancel()
                        await asyncio.gather(capture, return_exceptions=True)
                    reader.cancel()
            finally:
                await browser.close()


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    # Before browser creation this blocking read is the Job Object handshake.
    initial_line = sys.stdin.readline(1024 * 1024 + 2048)
    if not initial_line.endswith('\n'): raise ValueError('invalid_initial')
    initial = json.loads(initial_line)
    asyncio.run(browser_session(initial))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print('{"error":"session_unavailable"}', flush=True)
