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

# Since 10/2026 Smecel renders the class list with jQuery from code.jquery.com.
# The isolated Edge never contacts that CDN: this exact URL is answered from a
# bundled copy whose SHA-256 equals the official SRI (sha256-8WqyJLuW...).
# Every other third-party request stays blocked.
VENDORED_SCRIPTS = {
    "https://code.jquery.com/jquery-2.1.4.min.js": (
        "jquery-2.1.4.min.js", "f16ab224bb962910558715c82f58c10c3ed20f153ddfaa199029f141b5b0255c"),
}
VENDOR_DIR = Path(__file__).resolve().parents[1] / "assets" / "vendor"


def vendored_script(url):
    """Bytes for an approved CDN script, or None. A mismatching file is refused."""
    entry = VENDORED_SCRIPTS.get(url)
    if entry is None:
        return None
    import hashlib
    try:
        body = (VENDOR_DIR / entry[0]).read_bytes()
    except OSError:
        return None
    return body if hashlib.sha256(body).hexdigest() == entry[1] else None


NO_PRINT_JS = """Object.defineProperty(globalThis, 'print', {configurable: false, writable: false, value: () => undefined});"""

# The list is rendered once a row carries a class link; the placeholder rows
# shown while it loads have none. Independent of column count or order. Stop
# waiting as soon as the outcome is known: rows, or a login form that will never
# render them (an expired session used to wait the full 20 s timeout).
LIST_SETTLED_JS = """() => !!document.querySelector('#tbodyTurmas tr a[href*="vinculoAlunoExibirTurma.php"], input[type="password"]')"""

# Reading pages need no pictures, fonts or media. Aborting them keeps the six
# HTTP/1.1 connections free for the list request and the diary itself. This
# only refuses more: the allowed origin and every other block stay unchanged.
READ_PATHS = ("/sistema/escola/turmaListar.php", "/sistema/escola/diario_frequencia.php", "/sistema/escola/grade.php")
READ_SKIPPED_TYPES = {"image", "font", "media"}
# A list validated in this session is reused for the following diaries while
# the worker alone navigated the window, and for at most this many seconds.
CATALOG_REUSE_SECONDS = 300
LIST_PAGE_REUSE_SECONDS = 60


def reading_page_asset(request):
    if request.resource_type not in READ_SKIPPED_TYPES:
        return False
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(request.frame.url)
    except Exception:
        return False
    return parts.scheme == "https" and parts.hostname == "www.smecel.com.br" and parts.path in READ_PATHS

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
LOGIN_OPENER = 'button[onclick="abrirModal()"]:visible'


async def sign_in(page, email, password, *, reload=True):
    """Fill the Smecel form inside the isolated Edge only. The credential stays
    in this private worker; it is never logged, echoed or written to disk.

    reload=False is passed only when an expired session redirected the list
    to this exact login page seconds ago: loading it again repeats the same
    document. An older form is always reloaded before a password is typed."""
    if reload or getattr(page, "url", None) != LOGIN_URL:
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    if await page.locator('input[type="password"]').count() == 0:
        return {"logged_in": True}
    user, secret, submit = LOGIN_FIELDS
    if not await page.locator(user).is_visible():
        await page.click(LOGIN_OPENER)
    await page.fill(user, email)
    await page.fill(secret, password)
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
        await page.click(submit)
    return {"logged_in": await page.locator('input[type="password"]').count() == 0}


def browser_options(proxy, hidden=False):
    # Hidden = Edge's own headless mode: same engine, profile isolation, proxy
    # gate and request filter; only the window is not shown.
    return {"channel": "msedge", "headless": bool(hidden), "chromium_sandbox": True,
            "proxy": proxy.configuration,
            # HTTP/1.1 tunnels cannot coalesce an approved TLS connection across
            # origins; QUIC and non-proxied WebRTC UDP must not bypass the gate.
            "args": ["--disable-http2", "--disable-quic",
                     "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]}


def visible_identity(browser, hidden):
    """Hidden Edge announces itself as 'HeadlessEdg'; present the same user agent
    a visible Edge of this exact version sends (Chromium reduced format)."""
    if not hidden: return {}
    version = browser.version
    major = version.split(".", 1)[0]
    return {"user_agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                           f"Chrome/{major}.0.0.0 Safari/537.36 Edg/{major}.0.0.0")}


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
        script = vendored_script(route.request.url) if route.request.method == "GET" else None
        if script is not None:
            await route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=script)
        elif not allowed_request(route.request.url) or reading_page_asset(route.request):
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
    # The Smecel diary calls window.print() on load; in the isolated Edge that
    # opens a print dialog over every class. Reading never prints anything.
    await context.add_init_script(NO_PRINT_JS)


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
    def __init__(self, storage_state=None, hidden=False):
        self._storage_state = storage_state
        self.hidden = hidden
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
        initial = {"command": "open", "url": url, "hidden": self.hidden is True}
        if self._storage_state is not None: initial['storage_state'] = self._storage_state
        self._rpc(initial)
        self._storage_state = None

    def discover(self, year):
        return self._rpc({"command": "list", "year": year})

    def capture_selected(self, class_id, year, context_key):
        return self._rpc({"command": "capture", "class_id": class_id, "year": year, "context_key": context_key})

    def capture(self):
        return self._rpc({"command": "capture"})

    def schedule(self):
        # The school's weekly grid (owner decision 22/10/2026): one page, every class.
        return self._rpc({"command": "schedule"})

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
    from .class_schedule import grade_url, matches_grade, SCHEDULE_JS
    from urllib.parse import parse_qsl, urlsplit
    from playwright.async_api import async_playwright
    url = initial.get("url", "")
    params = dict(parse_qsl(urlsplit(url).query))
    listing_mode = matches_list(url, params.get("ano"))
    if initial.get("command") != "open" or not (listing_mode or matches_source(url, params.get("ct"), params.get("ano"))):
        raise ValueError("invalid_scope")
    with OriginProxy() as proxy:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**browser_options(proxy, initial.get("hidden") is True))
            try:
                context = await browser.new_context(accept_downloads=False, service_workers="block",
                                                    storage_state=initial.get('storage_state'),
                                                    **visible_identity(browser, initial.get("hidden") is True))
                page = await context.new_page()
                configure_page(page)
                await verify_proxy(page, proxy)
                await configure_context(context)
                # Navigation ownership. Only a page this worker loaded itself,
                # with no navigation since (user click, script redirect, login,
                # history change), may be reused; anything else forgets both
                # the loaded page and the validated list.
                owned = {"url": None, "at": 0.0, "expected": None, "redirected_at": None}
                catalogs = {}

                def forget():
                    owned["url"] = None
                    catalogs.clear()

                def navigated(frame):
                    if frame is page.main_frame and frame.url != owned["expected"]:
                        forget()
                        owned["redirected_at"] = time.monotonic()
                page.on("framenavigated", navigated)

                async def load(target):
                    owned["url"] = None
                    owned["expected"] = target
                    try:
                        await page.goto(target, wait_until="domcontentloaded")
                    finally:
                        owned["expected"] = None
                    if page.url == target:
                        owned["url"], owned["at"] = target, time.monotonic()

                try:
                    await load(url)
                except Exception:
                    pass
                print(json.dumps({"opened": True}), flush=True)
                async def read_catalog(year):
                    target = list_url(year)
                    if not (owned["url"] == target == page.url
                            and time.monotonic() - owned["at"] <= LIST_PAGE_REUSE_SECONDS):
                        await load(target)
                    before = page.url
                    if not matches_list(before, year):
                        raise ValueError("listing_changed")  # Login redirect: no rows will come.
                    try:
                        await page.wait_for_function(LIST_SETTLED_JS, timeout=20000)
                    except Exception:
                        pass  # Empty list: the observation below rejects it.
                    observation = await page.evaluate(CATALOG_JS)
                    if page.url != before or observation.get("url") != before:
                        raise ValueError("listing_changed")
                    catalog = catalog_from_observation(observation, year)
                    # The rendered page is consumed: a later read loads it again.
                    owned["url"] = None
                    catalogs[year] = (catalog, time.monotonic())
                    return catalog

                async def validated_catalog(year):
                    cached = catalogs.get(year)
                    if cached is not None and time.monotonic() - cached[1] <= CATALOG_REUSE_SECONDS:
                        return cached[0]
                    return await read_catalog(year)

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
                            redirected = owned["redirected_at"]
                            fresh_form = (page.url == LOGIN_URL and redirected is not None
                                          and time.monotonic() - redirected <= 30)
                            forget()
                            payload = await sign_in(page, str(command.get("email", "")), str(command.get("password", "")),
                                                    reload=not fresh_form)
                            print(json.dumps(payload), flush=True)
                            return
                        if command["command"] == "list":
                            payload = await read_catalog(command["year"])
                            print(json.dumps(payload, ensure_ascii=False), flush=True)
                            return
                        if command["command"] == "schedule":
                            # Only from the class list's session (the operational one); the grid
                            # page is read like the list: structured fields, never its HTML.
                            if not listing_mode:
                                raise ValueError("schedule_outside_list")
                            target = grade_url()
                            await load(target)
                            before = page.url
                            if not matches_grade(before):
                                payload = {"error": "schedule_unavailable"}  # Login redirect.
                            else:
                                payload = await page.evaluate(SCHEDULE_JS)
                                if page.url != before or payload.get("url") != before:
                                    payload = {"error": "page_changed"}
                            owned["url"] = None  # The list is loaded again when needed.
                            encoded = json.dumps(payload, ensure_ascii=False)
                            if len(encoded.encode("utf-8")) > MAX_REQUEST_BYTES:
                                encoded = '{"error":"transport_limit"}'
                            print(encoded, flush=True)
                            return
                        class_id, year = params.get("ct"), params.get("ano")
                        if listing_mode:
                            class_id, year = command.get("class_id"), command.get("year")
                            catalog = await validated_catalog(year)
                            if (catalog["scope"]["context_key"] != command.get("context_key")
                                    or class_id not in {c["class_id"] for c in catalog["classes"]}):
                                raise ValueError("selected_class_unavailable")
                            # Our own diary navigation keeps the list valid; a
                            # redirect (expired login) forgets it on the spot.
                            await load(source_url(class_id, year))
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
                        forget()
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
                            if command.get("command") not in {"capture", "list", "state", "login", "schedule"}:
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
