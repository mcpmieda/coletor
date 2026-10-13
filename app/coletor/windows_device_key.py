"""Candidate CNG device key adapter. Not wired into the app; no activation by default.

Only public ECDSA material can leave the Windows key storage provider. This key
does not itself grant access: the server must approve/revoke the device and
validate fresh, single-use challenges and the collector-only capability.
"""
import base64
import ctypes
from ctypes import wintypes
import hashlib
import struct
import sys

KEY_NAME = "Ecossistema.ColetorFrequencia.Device.v1"
TPM_PROVIDER = "Microsoft Platform Crypto Provider"
SOFTWARE_PROVIDER = "Microsoft Software Key Storage Provider"
SILENT = 0x40


class DeviceKeyError(Exception):
    def __init__(self, code="DEVICE_KEY_UNAVAILABLE"):
        self.code = code
        super().__init__("Não foi possível usar a chave protegida deste computador.")


class NativeCng:
    """Thin native API wrapper; instantiated lazily and never exports private blobs."""
    def __init__(self):
        if sys.platform != "win32":
            raise DeviceKeyError()
        self.dll = ctypes.WinDLL("ncrypt.dll", use_last_error=True)
        handle, pointer, word = ctypes.c_size_t, ctypes.c_void_p, wintypes.DWORD
        self._bind("NCryptOpenStorageProvider", [ctypes.POINTER(handle), wintypes.LPCWSTR, word])
        self._bind("NCryptCreatePersistedKey", [handle, ctypes.POINTER(handle), wintypes.LPCWSTR, wintypes.LPCWSTR, word, word])
        self._bind("NCryptOpenKey", [handle, ctypes.POINTER(handle), wintypes.LPCWSTR, word, word])
        self._bind("NCryptSetProperty", [handle, wintypes.LPCWSTR, pointer, word, word])
        self._bind("NCryptGetProperty", [handle, wintypes.LPCWSTR, pointer, word, ctypes.POINTER(word), word])
        self._bind("NCryptFinalizeKey", [handle, word])
        self._bind("NCryptExportKey", [handle, handle, wintypes.LPCWSTR, pointer, pointer, word, ctypes.POINTER(word), word])
        self._bind("NCryptSignHash", [handle, pointer, pointer, word, pointer, word, ctypes.POINTER(word), word])
        self._bind("NCryptDeleteKey", [handle, word])
        self._bind("NCryptFreeObject", [handle])

    def _bind(self, name, args):
        call = getattr(self.dll, name)
        call.argtypes, call.restype = args, ctypes.c_long

    def _check(self, status):
        if status != 0:
            raise DeviceKeyError()

    def provider(self, name):
        handle = ctypes.c_size_t()
        self._check(self.dll.NCryptOpenStorageProvider(ctypes.byref(handle), name, 0))
        return handle.value

    def create(self, provider):
        handle = ctypes.c_size_t()
        # Current user; no machine-wide scope and never overwrite an existing key.
        self._check(self.dll.NCryptCreatePersistedKey(provider, ctypes.byref(handle), "ECDSA_P256", KEY_NAME, 0, 0))
        return handle.value

    def open(self, provider):
        handle = ctypes.c_size_t()
        self._check(self.dll.NCryptOpenKey(provider, ctypes.byref(handle), KEY_NAME, 0, SILENT))
        return handle.value

    def set_dword(self, key, name, value):
        buffer = ctypes.create_string_buffer(struct.pack('<I', value))
        self._check(self.dll.NCryptSetProperty(key, name, buffer, 4, 0))

    def property(self, key, name):
        buffer, size = ctypes.create_string_buffer(512), wintypes.DWORD()
        self._check(self.dll.NCryptGetProperty(key, name, buffer, 512, ctypes.byref(size), SILENT))
        if size.value > 512:
            raise DeviceKeyError()
        return buffer.raw[:size.value]

    def finalize(self, key):
        self._check(self.dll.NCryptFinalizeKey(key, SILENT))

    def public_blob(self, key):
        buffer, size = ctypes.create_string_buffer(72), wintypes.DWORD()
        self._check(self.dll.NCryptExportKey(key, 0, "ECCPUBLICBLOB", None, buffer, 72, ctypes.byref(size), SILENT))
        if size.value != 72:
            raise DeviceKeyError()
        return buffer.raw

    def sign_digest(self, key, digest):
        source, output, size = ctypes.create_string_buffer(digest), ctypes.create_string_buffer(64), wintypes.DWORD()
        self._check(self.dll.NCryptSignHash(key, None, source, len(digest), output, 64, ctypes.byref(size), SILENT))
        if size.value != 64:
            raise DeviceKeyError()
        return output.raw

    def delete(self, key):
        self._check(self.dll.NCryptDeleteKey(key, SILENT))

    def free(self, handle):
        self._check(self.dll.NCryptFreeObject(handle))


class WindowsDeviceKey:
    def __init__(self, *, crypto=None, provider=TPM_PROVIDER):
        if provider not in {TPM_PROVIDER, SOFTWARE_PROVIDER}:
            raise DeviceKeyError()
        self._crypto, self._provider_name = crypto, provider
        self._provider = self._key = None

    def _prepare(self):
        if self._crypto is None:
            self._crypto = NativeCng()
        if self._provider is None:
            self._provider = self._crypto.provider(self._provider_name)

    def _validate(self):
        if self._key is None:
            raise DeviceKeyError()
        properties = {name: self._crypto.property(self._key, name)
                      for name in ('Export Policy', 'Length', 'Key Usage', 'Algorithm Group')}
        if (properties['Export Policy'] != struct.pack('<I', 0)
                or properties['Length'] != struct.pack('<I', 256)
                or properties['Key Usage'] != struct.pack('<I', 2)
                or properties['Algorithm Group'].decode('utf-16-le').rstrip('\0') != 'ECDSA'):
            raise DeviceKeyError('DEVICE_KEY_POLICY_MISMATCH')

    def create(self, *, activation_authorized=False):
        # Governance check is Python-only; never expose this switch through JS.
        if activation_authorized is not True or self._key is not None:
            raise DeviceKeyError('DEVICE_ACTIVATION_NOT_AUTHORIZED')
        try:
            self._prepare()
            self._key = self._crypto.create(self._provider)
            self._crypto.set_dword(self._key, 'Export Policy', 0)
            self._crypto.set_dword(self._key, 'Key Usage', 2)
            self._crypto.finalize(self._key)
            self._validate()
            return self.public_jwk()
        except Exception:
            # A newly created failed key must not silently become a credential.
            if self._key is not None:
                try:
                    self._crypto.delete(self._key)
                    self._key = None
                except Exception:
                    pass
            self.close()
            raise DeviceKeyError() from None

    def load(self):
        try:
            if self._key is not None:
                raise DeviceKeyError()
            self._prepare()
            self._key = self._crypto.open(self._provider)
            self._validate()
            return self.public_jwk()
        except Exception:
            self.close()
            raise DeviceKeyError() from None

    def public_jwk(self):
        self._validate()
        blob = self._crypto.public_blob(self._key)
        if not isinstance(blob, bytes) or len(blob) != 72 or struct.unpack('<II', blob[:8]) != (0x31534345, 32):
            raise DeviceKeyError()
        encode = lambda value: base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')
        return {'kty': 'EC', 'crv': 'P-256', 'x': encode(blob[8:40]), 'y': encode(blob[40:72]), 'ext': True}

    def sign_challenge(self, challenge):
        if not isinstance(challenge, bytes) or not 32 <= len(challenge) <= 1024:
            raise DeviceKeyError('INVALID_DEVICE_CHALLENGE')
        self._validate()
        digest = hashlib.sha256(b'Ecossistema.Coletor.DeviceProof.v1\0' + challenge).digest()
        signature = self._crypto.sign_digest(self._key, digest)
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise DeviceKeyError()
        return base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')

    def forget(self, *, removal_authorized=False):
        if removal_authorized is not True:
            raise DeviceKeyError('DEVICE_REMOVAL_NOT_AUTHORIZED')
        if self._key is None:
            self.load()
        self._crypto.delete(self._key)
        self._key = None  # NCryptDeleteKey also consumes the handle.
        self.close()

    def close(self):
        for field in ('_key', '_provider'):
            handle = getattr(self, field)
            if handle is not None:
                self._crypto.free(handle)
                setattr(self, field, None)
