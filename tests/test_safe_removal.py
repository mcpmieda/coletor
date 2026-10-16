import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from coletor.__main__ import main
from coletor.device_provider import DeviceProvider
from coletor.institutional_access import AccessDenied, OFFICIAL_ORIGIN
from coletor.safe_removal import run
from coletor.windows_device_key import WindowsDeviceKey, DeviceKeyError
from test_device_provider import SyntheticTransport, NOW, DEVICE
from test_windows_device_key import FakeCrypto


class SafeRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'only-this-device'
        self.crypto, self.transport = FakeCrypto(), SyntheticTransport()
        self.factory = Mock(side_effect=lambda **kw: WindowsDeviceKey(crypto=self.crypto, **kw))
        self.browser = Mock(return_value=False)
        self.provider = self.make_provider()
        self.output = io.StringIO()

    def make_provider(self):
        return DeviceProvider(self.root, transport=self.transport, key_factory=self.factory,
                              consent=lambda *args: True, browser=self.browser, clock=lambda: NOW)

    def activate_fake(self):
        self.provider._browser = Mock(return_value=True)
        self.provider.open_official_login()
        self.transport.completed = True
        self.provider.verify_online()
        self.provider.release()
        self.provider = self.make_provider()

    def tearDown(self):
        self.provider.release()
        self.temporary.cleanup()

    def test_no_record_opens_no_key_network_browser_or_directory(self):
        self.assertEqual(run(provider=self.provider, output=self.output), 0)
        self.assertFalse(self.root.exists())
        self.factory.assert_not_called()
        self.assertEqual(self.transport.calls, [])
        self.browser.assert_not_called()
        self.assertIn('Nenhuma chave foi verificada ou apagada', self.output.getvalue())

    def test_online_cleanup_preserves_preferences_and_other_device_record(self):
        self.activate_fake()
        preferences = self.root / 'settings.json'
        preferences.write_bytes(b'{"theme":"dark"}')
        other = self.root.parent / 'another-device.json'
        other.write_bytes(b'other-device-unchanged')
        self.transport.calls.clear()
        self.assertEqual(run(provider=self.provider, output=self.output), 0)
        self.assertFalse(self.crypto.exists)
        self.assertFalse((self.root / 'device.json').exists())
        self.assertEqual(preferences.read_bytes(), b'{"theme":"dark"}')
        self.assertEqual(other.read_bytes(), b'other-device-unchanged')
        self.assertEqual([call[1] for call in self.transport.calls], ['challenge', 'revoke'])
        self.assertTrue(all(call[2]['deviceId'] == DEVICE for call in self.transport.calls))
        self.browser.assert_not_called()

    def test_offline_deletes_key_but_reports_public_device_with_no_queue_promise(self):
        self.activate_fake()
        self.transport.request = Mock(side_effect=AccessDenied('ACCESS_UNAVAILABLE'))
        self.assertEqual(run(provider=self.provider, output=self.output), 2)
        self.assertFalse(self.crypto.exists)
        self.assertEqual(self.provider.removal_status(), {'state': 'revokedLocally', 'deviceId': DEVICE})
        message = self.output.getvalue()
        self.assertIn('NÃO foi confirmada', message)
        self.assertIn(OFFICIAL_ORIGIN + '/frequency-collector/revoke?device=' + DEVICE, message)
        self.assertIn('nenhuma fila', message)
        self.assertNotIn('signature', message)
        self.assertNotIn('pollToken', message)
        self.browser.assert_not_called()

    def test_offline_repeat_never_recreates_or_redeletes_key(self):
        self.activate_fake()
        self.transport.request = Mock(side_effect=AccessDenied('ACCESS_UNAVAILABLE'))
        self.assertEqual(run(provider=self.provider, output=self.output), 2)
        count = self.factory.call_count
        self.provider = self.make_provider()
        self.assertEqual(run(provider=self.provider, output=io.StringIO()), 2)
        self.assertEqual(self.factory.call_count, count)
        self.assertFalse(self.crypto.exists)

    def test_key_deletion_failure_never_claims_local_success(self):
        self.activate_fake()
        self.crypto.delete = Mock(side_effect=DeviceKeyError())
        self.assertEqual(run(provider=self.provider, output=self.output), 1)
        self.assertTrue(self.crypto.exists)
        self.assertEqual(self.provider.removal_status()['state'], 'deletePending')
        self.assertIn('Limpeza local não concluída', self.output.getvalue())

    def test_invalid_record_does_not_open_key_or_echo_file(self):
        self.root.mkdir()
        (self.root / 'device.json').write_bytes(b'synthetic-private-input')
        self.assertEqual(run(provider=self.provider, output=self.output), 1)
        self.factory.assert_not_called()
        self.assertEqual(self.transport.calls, [])
        self.assertNotIn('synthetic-private-input', self.output.getvalue())


    def test_safe_removal_blocks_unconfirmed_encrypted_queue_even_offline(self):
        self.activate_fake()
        from coletor.protected_storage import ProtectedStorage
        # This separate process cannot assume it can read a saved DPAPI
        # generation; the encrypted queue's mere presence must fail closed.
        storage = ProtectedStorage(self.root)
        storage.directory.mkdir(parents=True, exist_ok=True)
        queue = storage.directory / 'queue.dpapi'
        queue.write_bytes(b'CFV2\\0SYNTHETIC-UNRECEIPTED-DPAPI')
        original = queue.read_bytes()
        self.transport.calls.clear()
        self.transport.request = Mock(side_effect=AccessDenied('ACCESS_UNAVAILABLE'))
        self.assertEqual(run(provider=self.provider, output=self.output), 1)
        self.assertEqual(queue.read_bytes(), original)
        self.assertTrue(self.crypto.exists)
        self.assertEqual(self.transport.calls, [])
        self.assertIn('Remoção bloqueada', self.output.getvalue())

    def test_safe_removal_blocks_queue_without_device_metadata(self):
        from coletor.protected_storage import ProtectedStorage
        storage = ProtectedStorage(self.root)
        storage.directory.mkdir(parents=True, exist_ok=True)
        queue = storage.directory / 'queue.dpapi'
        queue.write_bytes(b'CFV2\\0OLD-ENCRYPTED-QUEUE')
        self.assertEqual(run(provider=self.provider, output=self.output), 1)
        self.assertEqual(queue.read_bytes(), b'CFV2\\0OLD-ENCRYPTED-QUEUE')
        self.factory.assert_not_called()
        self.assertEqual(self.transport.calls, [])

    def test_cli_dispatch_does_not_start_desktop_or_preview(self):
        with patch('coletor.safe_removal.run', return_value=2) as action:
            self.assertEqual(main(['--safe-removal']), 2)
            action.assert_called_once_with()
        for extra in ('--preview-server', '--dev'):
            with self.subTest(extra=extra), patch('coletor.safe_removal.run') as action, patch('sys.stderr', io.StringIO()):
                with self.assertRaises(SystemExit):
                    main(['--safe-removal', extra])
                action.assert_not_called()
