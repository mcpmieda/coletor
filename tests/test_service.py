import json
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from coletor.server import PreviewServer
from coletor.service import PreviewApi, preview


class PreviewServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = PreviewServer(0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        result = (response.status, dict(response.headers), response.read())
        conn.close()
        return result

    def test_demo_is_synthetic_and_cannot_send(self):
        status, headers, data = self.request('GET', '/api/demo')
        self.assertEqual(status, 200)
        body = json.loads(data)
        self.assertEqual(body['mode'], 'demo')
        self.assertFalse(body['validation']['allowed'])
        self.assertTrue(body['snapshot']['students'])
        self.assertTrue(all('sint' in s['display_name'].lower() for s in body['snapshot']['students']))
        self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_dns_rebinding_host_rejected(self):
        self.assertEqual(self.request('GET', '/api/demo', headers={'Host':'untrusted.example'})[0], 403)

    def test_cross_origin_post_rejected(self):
        self.assertEqual(self.request('POST', '/api/preview', body='{}', headers={'Origin':'https://untrusted.example', 'Content-Type':'application/json'})[0], 403)

    def test_missing_origin_post_rejected(self):
        self.assertEqual(self.request('POST', '/api/preview', body='{}', headers={'Content-Type':'application/json'})[0], 403)

    def test_valid_preview_preserves_block(self):
        data = json.dumps({'html':'<html>login</html>', 'class_id':'TESTE-A', 'year':2026})
        status, _, payload = self.request('POST','/api/preview', data, {'Origin':f'http://127.0.0.1:{self.port}', 'Content-Type':'application/json'})
        self.assertEqual(status,200)
        self.assertFalse(json.loads(payload)['validation']['allowed'])

    def test_invalid_json_no_input_echo(self):
        status, _, payload = self.request('POST', '/api/preview', '{"private":"DO_NOT_ECHO"}', {'Origin':f'http://127.0.0.1:{self.port}', 'Content-Type':'application/json'})
        self.assertEqual(status,400)
        self.assertNotIn(b'DO_NOT_ECHO', payload)

    def test_traversal_blocked(self):
        self.assertEqual(self.request('GET','/../../app/coletor/server.py')[0],404)

    def test_no_transmission_endpoint(self):
        self.assertEqual(self.request('POST','/api/send','{}', {'Origin':f'http://127.0.0.1:{self.port}'})[0],404)

    def test_native_api_exposes_only_preview(self):
        self.assertEqual([n for n in dir(PreviewApi()) if not n.startswith('_')], ['load_demo', 'preview_html'])
        self.assertFalse(PreviewApi().load_demo()['validation']['allowed'])

    def test_native_api_rejects_large_or_invalid_input(self):
        self.assertIn('error',PreviewApi().preview_html('x' * (8*1024*1024+1),'TESTE-A',2026))
        self.assertIn('error',PreviewApi().preview_html('html','TESTE-A',True))
        self.assertIn('error',PreviewApi().preview_html('html','',2026))


if __name__ == '__main__': unittest.main()
