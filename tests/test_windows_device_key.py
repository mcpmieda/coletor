import base64
import struct
import unittest
from coletor.windows_device_key import (DeviceKeyError, WindowsDeviceKey,
    TPM_PROVIDER, SOFTWARE_PROVIDER)


class FakeCrypto:
    """Policy/call tests only. No Windows key, private key or account is created."""
    def __init__(self):
        self.calls = []
        self.exists = False
        self.properties = {'Export Policy': struct.pack('<I', 0),
                           'Length': struct.pack('<I', 256),
                           'Key Usage': struct.pack('<I', 2),
                           'Algorithm Group': 'ECDSA\0'.encode('utf-16-le')}

    def provider(self, name):
        self.calls.append(('provider', name))
        return 1

    def create(self, provider):
        self.calls.append(('create', provider))
        if self.exists:
            raise RuntimeError('exists')
        self.exists = True
        return 2

    def open(self, provider):
        self.calls.append(('open', provider))
        if not self.exists:
            raise DeviceKeyError('DEVICE_KEY_MISSING')
        return 2

    def set_dword(self, key, name, value):
        self.calls.append(('set', name, value))
        self.properties[name] = struct.pack('<I', value)

    def property(self, key, name):
        return self.properties[name]

    def finalize(self, key):
        self.calls.append(('finalize', key))

    def public_blob(self, key):
        self.calls.append(('public_only', key))
        return struct.pack('<II', 0x31534345, 32) + bytes(range(64))

    def sign_digest(self, key, digest):
        self.calls.append(('sign', digest))
        return bytes(range(64))

    def delete(self, key):
        self.calls.append(('delete', key))
        self.exists = False

    def free(self, handle):
        self.calls.append(('free', handle))


class WindowsDeviceKeyTests(unittest.TestCase):
    def test_default_never_creates_persistent_key_without_activation(self):
        crypto = FakeCrypto()
        key = WindowsDeviceKey(crypto=crypto)
        for permission in [False, None, 1, 'true']:
            with self.assertRaises(DeviceKeyError):
                key.create(activation_authorized=permission)
        self.assertEqual(crypto.calls, [])

    def test_creation_enforces_nonexportable_sign_only_and_public_material(self):
        crypto = FakeCrypto()
        jwk = WindowsDeviceKey(crypto=crypto).create(activation_authorized=True)
        self.assertIn(('provider', TPM_PROVIDER), crypto.calls)
        self.assertIn(('set', 'Export Policy', 0), crypto.calls)
        self.assertIn(('set', 'Key Usage', 2), crypto.calls)
        self.assertEqual(set(jwk), {'kty', 'crv', 'x', 'y', 'ext'})
        self.assertNotIn('d', jwk)

    def test_close_releases_handles_and_retains_key_for_next_launch(self):
        crypto = FakeCrypto()
        first = WindowsDeviceKey(crypto=crypto)
        expected = first.create(activation_authorized=True)
        first.close()
        self.assertTrue(crypto.exists)
        second = WindowsDeviceKey(crypto=crypto)
        self.assertEqual(second.load(), expected)
        self.assertEqual(sum(call[0] == 'create' for call in crypto.calls), 1)

    def test_missing_key_does_not_silently_replace_or_authorize_device(self):
        crypto = FakeCrypto()
        with self.assertRaises(DeviceKeyError):
            WindowsDeviceKey(crypto=crypto).load()
        self.assertFalse(crypto.exists)
        self.assertFalse(any(call[0] == 'create' for call in crypto.calls))

    def test_existing_key_policy_drift_is_rejected_without_delete(self):
        for name, value in [('Export Policy', struct.pack('<I', 1)),
                            ('Length', struct.pack('<I', 384)),
                            ('Key Usage', struct.pack('<I', 0xffffffff)),
                            ('Algorithm Group', 'RSA\0'.encode('utf-16-le'))]:
            crypto = FakeCrypto()
            crypto.exists = True
            crypto.properties[name] = value
            with self.subTest(name=name), self.assertRaises(DeviceKeyError):
                WindowsDeviceKey(crypto=crypto).load()
            self.assertTrue(crypto.exists)
            self.assertFalse(any(call[0] == 'delete' for call in crypto.calls))

    def test_no_automatic_tpm_to_software_downgrade(self):
        class Unavailable(FakeCrypto):
            def provider(self, name):
                self.calls.append(('provider', name))
                raise RuntimeError('TPM unavailable')
        crypto = Unavailable()
        with self.assertRaises(DeviceKeyError):
            WindowsDeviceKey(crypto=crypto).create(activation_authorized=True)
        self.assertEqual(crypto.calls, [('provider', TPM_PROVIDER)])
        self.assertNotIn(('provider', SOFTWARE_PROVIDER), crypto.calls)

    def test_challenge_signature_is_bounded_and_domain_separated(self):
        crypto = FakeCrypto()
        key = WindowsDeviceKey(crypto=crypto)
        key.create(activation_authorized=True)
        for invalid in [None, 'nonce', b'x'*31, b'x'*1025]:
            with self.assertRaises(DeviceKeyError):
                key.sign_challenge(invalid)
        value = key.sign_challenge(b'x'*32)
        self.assertEqual(len(base64.urlsafe_b64decode(value+'==')), 64)
        digest = [call[1] for call in crypto.calls if call[0] == 'sign'][0]
        import hashlib
        self.assertNotEqual(digest, hashlib.sha256(b'x'*32).digest())

    def test_explicit_removal_deletes_only_managed_key_and_consumes_handle(self):
        crypto = FakeCrypto()
        key = WindowsDeviceKey(crypto=crypto)
        key.create(activation_authorized=True)
        with self.assertRaises(DeviceKeyError):
            key.forget()
        self.assertTrue(crypto.exists)
        key.forget(removal_authorized=True)
        self.assertFalse(crypto.exists)
        self.assertEqual(sum(call == ('delete', 2) for call in crypto.calls), 1)
        self.assertNotIn(('free', 2), crypto.calls)

    def test_existing_key_is_never_overwritten_on_creation_failure(self):
        crypto = FakeCrypto()
        crypto.exists = True
        with self.assertRaises(DeviceKeyError):
            WindowsDeviceKey(crypto=crypto).create(activation_authorized=True)
        self.assertTrue(crypto.exists)
        self.assertFalse(any(call[0] == 'delete' for call in crypto.calls))

    def test_ecdh_public_blob_is_rejected_for_signing_key(self):
        class WrongBlob(FakeCrypto):
            def public_blob(self, key):
                return struct.pack('<II', 0x314B4345, 32) + bytes(range(64))
        crypto = WrongBlob()
        with self.assertRaises(DeviceKeyError):
            WindowsDeviceKey(crypto=crypto).create(activation_authorized=True)
        self.assertFalse(crypto.exists)


if __name__ == '__main__':
    unittest.main()
