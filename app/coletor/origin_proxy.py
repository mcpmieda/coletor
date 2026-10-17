"""Ephemeral loopback CONNECT gate: every TLS destination is checked before dial.

No TLS interception, certificate installation, request/body logging or cookies.
Redirects retain normal browser semantics but cannot tunnel to another origin.
"""
import asyncio
import select
import socket
import socketserver
import threading
import time

AUTHORITY = b"www.smecel.com.br:443"
OPENING_HTML = ('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Abrindo o Smecel…</title>'
                '<body style="margin:0;display:grid;place-items:center;height:100vh;font:16px system-ui;'
                'color:#5b4b52;background:#faf7f8">Abrindo o Smecel…</body></html>')
PROBE_FRAME_JS = """url => { const frame = document.createElement('iframe'); frame.hidden = true;
  frame.src = url; document.body.appendChild(frame); }"""


async def verify_proxy(page, proxy):
    """Fail closed before source navigation if Edge bypasses our proxy settings."""
    class Probe(socketserver.BaseRequestHandler):
        def handle(self):
            self.server.contacts += 1
            self.request.settimeout(2)
            try:
                self.request.recv(4096)
                self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Probe)
    server.daemon_threads = True
    server.contacts = 0
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    before = proxy.denied_connections
    try:
        # Probe from a hidden frame: navigating the visible tab to the denied
        # address flashed Edge's "access denied" page before Smecel opened.
        await page.set_content(OPENING_HTML)
        await page.evaluate(PROBE_FRAME_JS, f"http://127.0.0.1:{server.server_address[1]}/source-isolation-probe")
        deadline = time.monotonic() + 3
        while server.contacts == 0 and proxy.denied_connections <= before and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if server.contacts != 0 or proxy.denied_connections <= before:
            raise RuntimeError("browser_proxy_not_enforced")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


class OriginProxy:
    def __init__(self, dial=None):
        self._dial = dial or (lambda: socket.create_connection(("www.smecel.com.br", 443), timeout=10))
        self._lock = threading.Lock()
        self._sockets = set()
        self._capacity = threading.BoundedSemaphore(16)
        self.denied_connections = 0
        self.allowed_connections = 0
        owner = self

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                if not owner._capacity.acquire(blocking=False):
                    return
                upstream = None
                owner._track(self.request, True)
                try:
                    self.request.settimeout(10)
                    header = bytearray()
                    while b"\r\n\r\n" not in header and len(header) <= 8192:
                        block = self.request.recv(1)
                        if not block:
                            return
                        header.extend(block)
                    first = bytes(header).split(b"\r\n", 1)[0].split(b" ")
                    if (len(header) > 8192 or len(first) != 3 or first[0] != b"CONNECT"
                            or first[1].lower() != AUTHORITY or first[2] not in (b"HTTP/1.0", b"HTTP/1.1")):
                        with owner._lock:
                            owner.denied_connections += 1
                        self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                        return
                    # Denied destinations are never resolved or contacted, including
                    # redirect destinations carrying a POST body or authorization.
                    upstream = owner._dial()
                    owner._track(upstream, True)
                    with owner._lock:
                        owner.allowed_connections += 1
                    self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    self.request.settimeout(None)
                    upstream.settimeout(None)
                    while True:
                        readable, _, _ = select.select([self.request, upstream], [], [], 1)
                        for source in readable:
                            data = source.recv(65536)
                            if not data:
                                return
                            destination = upstream if source is self.request else self.request
                            destination.sendall(data)
                except (OSError, ValueError):
                    pass
                finally:
                    if upstream is not None:
                        owner._track(upstream, False)
                        upstream.close()
                    owner._track(self.request, False)
                    owner._capacity.release()

        self._server = Server(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)

    def _track(self, connection, add):
        with self._lock:
            if add:
                self._sockets.add(connection)
            else:
                self._sockets.discard(connection)

    @property
    def configuration(self):
        return {"server": f"http://127.0.0.1:{self._server.server_address[1]}", "bypass": "<-loopback>"}

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._server.shutdown()
        self._server.server_close()
        with self._lock:
            connections = list(self._sockets)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        self._thread.join(timeout=2)
