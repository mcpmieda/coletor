"""Loopback-only synthetic TLS source and denied-destination contact counter.

Temporary self-signed QA key, never installed in trust stores or packaged.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit


class SyntheticHttps:
    def __init__(self, html):
        self.html = html
        self.contacts = 0
        self.alpns = []
        self.post_checks = []
        owner = self
        class Denied(socketserver.BaseRequestHandler):
            def handle(self):
                owner.contacts += 1  # Any TCP contact fails QA, even before TLS/body.
        self.denied = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Denied)
        self.denied.daemon_threads = True
        self.destination = f'https://127.0.0.1:{self.denied.server_address[1]}/denied'
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_):
                pass
            def do_GET(self):
                self.reply()
            def do_POST(self):
                length = int(self.headers.get('Content-Length', '0'))
                body = self.rfile.read(min(length, 1024))
                owner.post_checks.append(body == b'SYNTHETIC_CREDENTIAL_FIXTURE_ONLY')
                self.reply()
            def reply(self):
                path = urlsplit(self.path).path
                owner.alpns.append(self.connection.selected_alpn_protocol())
                if path in ('/qa-redirect-get', '/qa-post307', '/qa-post308'):
                    status = 302 if path.endswith('get') else 307 if path.endswith('307') else 308
                    self.send_response(status)
                    self.send_header('Location', owner.destination)
                    body = b''
                elif path == '/qa-allowed-redirect':
                    self.send_response(302)
                    self.send_header('Location', '/qa-target')
                    body = b''
                else:
                    self.send_response(200)
                    self.send_header('Set-Cookie', 'coletor_synthetic_qa=fixture-only; Secure; HttpOnly; Path=/')
                    body = (owner.html if path != '/qa-target' else 'synthetic redirect arrived').encode('utf-8')
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.source = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.source.daemon_threads = True

    def __enter__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='coletor-synthetic-tls-')
        root = Path(self.temporary.name)
        openssl = shutil.which('openssl')
        if not openssl and sys.platform == 'win32':
            candidate = Path('C:/Program Files/Git/usr/bin/openssl.exe')
            openssl = str(candidate) if candidate.is_file() else None
        if not openssl:
            raise RuntimeError('synthetic_tls_tool_missing')
        command = [openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                   '-subj', '/CN=www.smecel.com.br', '-addext', 'subjectAltName=DNS:www.smecel.com.br',
                   '-keyout', str(root/'key.pem'), '-out', str(root/'certificate.pem')]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(root/'certificate.pem', root/'key.pem')
        context.set_alpn_protocols(['h2', 'http/1.1'])
        self.source.socket = context.wrap_socket(self.source.socket, server_side=True)
        self.threads = [threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
                        for server in (self.source, self.denied)]
        for thread in self.threads:
            thread.start()
        return self

    def dial(self):
        return socket.create_connection(self.source.server_address, timeout=5)

    def __exit__(self, *_):
        for server in (self.source, self.denied):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(2)
        self.temporary.cleanup()
