"""Destination checks happen before DNS/dial, without TLS/body inspection."""
import socket
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from coletor.origin_proxy import OriginProxy


class OriginProxyTests(unittest.TestCase):
    def test_denied_connect_and_plain_http_never_dial_any_destination(self):
        calls = []
        def dial():
            calls.append(True)
            raise AssertionError('A denied target must never be contacted')
        with OriginProxy(dial) as proxy:
            port = int(proxy.configuration['server'].rsplit(':', 1)[1])
            for target in (b'evil.invalid:443', b'www.smecel.com.br.evil.invalid:443',
                           b'www.smecel.com.br:444', b'user@www.smecel.com.br:443',
                           b'127.0.0.1:443'):
                with socket.create_connection(('127.0.0.1', port), timeout=2) as connection:
                    connection.sendall(b'CONNECT ' + target + b' HTTP/1.1\r\nHost: ignored\r\n\r\nSYNTHETIC_BODY')
                    self.assertIn(b'403', connection.recv(256))
            with socket.create_connection(('127.0.0.1', port), timeout=2) as connection:
                connection.sendall(b'GET http://www.smecel.com.br/ HTTP/1.1\r\n\r\n')
                self.assertIn(b'403', connection.recv(256))
            self.assertEqual(calls, [])
            self.assertEqual(proxy.denied_connections, 6)
        with self.assertRaises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=1)


if __name__ == '__main__':
    unittest.main()
