"""Loopback-only preview server. It never fetches, persists or transmits a diary."""
from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from .service import preview, ROOT, MAX_HTML_BYTES
from .demo import build_fixture
MAX_REQUEST_BYTES = 10 * 1024 * 1024


class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int = 8765, dev: bool = False):
        self.dev = dev
        super().__init__(("127.0.0.1", port), PreviewHandler)


class PreviewHandler(BaseHTTPRequestHandler):
    server: PreviewServer
    server_version = "LocalPreview/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # Do not log bodies, document names, pupils, headers or credentials.
        return

    def _trusted(self, require_origin: bool = False) -> bool:
        port = self.server.server_address[1]
        origin = f"http://127.0.0.1:{port}"
        if self.headers.get("Host") != f"127.0.0.1:{port}":
            return False
        incoming = self.headers.get("Origin")
        allowed = {origin}
        if self.server.dev:
            allowed.add("http://127.0.0.1:5173")
        return incoming in allowed if require_origin else incoming is None or incoming in allowed

    def _send(self, code: int, data: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, data: dict):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        if not self._trusted():
            self._json(403, {"error": "Origem local inválida."})
            return
        path = urlsplit(self.path).path
        if path == "/api/demo":
            try:
                fixture = build_fixture()
                self._json(200, preview(fixture, "TESTE-A", 2026, "demo"))
            except (OSError, ValueError):
                self._json(500, {"error": "A demonstração não está disponível neste pacote."})
            return
        if path.startswith("/api/"):
            self._json(404, {"error": "Recurso não disponível."})
            return
        root = (ROOT / "ui/dist").resolve()
        target = (root / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            self._json(404, {"error": "Interface não encontrada. Execute o build da interface."})
            return
        self._send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")

    def do_POST(self):
        if not self._trusted(require_origin=True):
            self._json(403, {"error": "Origem local inválida."})
            return
        if urlsplit(self.path).path != "/api/preview":
            self._json(404, {"error": "Recurso não disponível."})
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json" or self.headers.get("Transfer-Encoding"):
            self._json(415, {"error": "Use um corpo JSON de tamanho conhecido."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_REQUEST_BYTES:
            self._json(413, {"error": "Arquivo ausente ou maior que o limite de 8 MB."})
            return
        try:
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or set(body) != {"html", "class_id", "year"}:
                raise ValueError("schema")
            html, class_id, year = body["html"], body["class_id"], body["year"]
            if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_HTML_BYTES:
                raise ValueError("html")
            if not isinstance(class_id, str) or not class_id.strip() or len(class_id) > 80:
                raise ValueError("class")
            if type(year) is not int or not 2000 <= year <= 2100:
                raise ValueError("year")
            self._json(200, preview(html, class_id.strip(), year))
        except (ValueError, TypeError, KeyError, RecursionError):
            self._json(400, {"error": "Não foi possível ler o diário. Confira o HTML, a turma e o ano."})


def serve(port: int = 8765, dev: bool = False):
    server = PreviewServer(port, dev)
    print(f"Prévia local: http://127.0.0.1:{server.server_address[1]} (sem envio)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
