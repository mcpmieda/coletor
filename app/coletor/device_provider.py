"""Collector-only online provider. Microsoft passwords/tokens never enter the PC.

Construction/status without device state creates no credential and sends no
request. New activation requires server readiness and a native human decision.
Production TLS transport has one fixed origin, no redirect/cookie/proxy support.
"""
import base64
import ctypes
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import tempfile
import threading
import time
import uuid
import webbrowser

from .institutional_access import AccessDenied, OnlineResponse, OFFICIAL_ORIGIN
from .local_settings import LocalSettings, user_settings_directory
from .windows_device_key import WindowsDeviceKey, DeviceKeyError, TPM_PROVIDER, SOFTWARE_PROVIDER

PREFIX = '/api/frequency-collector/'
PATHS = {PREFIX + p for p in ('config', 'pairings', 'pairings/poll', 'pairings/cancel', 'pairings/claim', 'challenge', 'access', 'revoke', 'device-status', 'frequency')}
FREQUENCY_BYTES = 16 * 1024 * 1024
FREQUENCY_ERRORS = {'invalid-request', 'not-authorized', 'unavailable', 'revision-conflict', 'lease-busy', 'lease-fenced', 'paused', 'source-invalid', 'identity-review'}


def launch_system_browser(url, new=2, *, platform=None, shell_execute=None):
    """Open a fixed-origin collector page using the Windows URL association.

    Python's webbrowser registry is unreliable in embedded pythonw.exe builds.
    ShellExecuteW uses the configured Windows HTTPS association directly.
    The native OS result proves dispatch, not that a page has loaded.
    """
    if (not isinstance(url, str)
            or not url.startswith(OFFICIAL_ORIGIN + '/frequency-collector/')):
        return False
    if (os.name if platform is None else platform) != 'nt':
        try:
            return bool(webbrowser.open(url, new=new))
        except (OSError, RuntimeError):
            return False
    try:
        shell = shell_execute
        if shell is None:
            shell = ctypes.windll.shell32.ShellExecuteW
            shell.restype = ctypes.c_void_p
        result = shell(None, 'open', url, None, None, 1)
        return result is not None and int(result) > 32
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def canonical_frequency(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


class FrequencyError(AccessDenied):
    """A sanitized operational code, never a backend exception or source data."""
    pass


def compact(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def decode(response):
    if not isinstance(response, OnlineResponse) or response.status != 200 or len(response.body) > 8192:
        raise AccessDenied('ACCESS_UNAVAILABLE')
    try:
        value = json.loads(response.body, object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise AccessDenied('INVALID_ACCESS_RESPONSE') from None


def thumbprint(public):
    raw = compact({name: public[name] for name in ('crv', 'kty', 'x', 'y')})
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode('ascii').rstrip('=')


class OfficialTransport:
    def __init__(self, *, connection=None):
        self._connection = connection

    def request(self, method, path, value=None):
        if path not in PATHS or method not in {'GET', 'POST'} or (method == 'GET') != (path == PREFIX + 'config'):
            raise AccessDenied('INVALID_ACCESS_REQUEST')
        frequency = path == PREFIX + 'frequency'
        limit = FREQUENCY_BYTES if frequency else 8192
        payload = canonical_frequency(value) if frequency else compact(value) if value is not None else None
        if payload is not None and len(payload) > (FREQUENCY_BYTES if frequency else 2048):
            raise AccessDenied('INVALID_ACCESS_REQUEST')
        connection = (self._connection or (lambda: http.client.HTTPSConnection(
            'admin.escolaieda.com', 443, timeout=10, context=ssl.create_default_context())))()
        try:
            connection.request(method, path, body=payload,
                               headers={'Accept': 'application/json', 'Content-Type': 'application/json', 'Cache-Control': 'no-store'})
            reply = connection.getresponse()
            length = reply.getheader('Content-Length')
            if ((reply.status != 200 and not (frequency and reply.status in {400, 401, 403, 409, 503}))
                    or reply.getheader('Content-Encoding') not in (None, 'identity')
                    or not (reply.getheader('Content-Type') or '').lower().startswith('application/json')
                    or length is not None and (not length.isdigit() or int(length) > limit)):
                # A specific, bounded, official 503 JSON response distinguishes
                # disabled server configuration from ordinary unavailability.
                if path == PREFIX+'config' and reply.status == 503:
                    raw_error=reply.read(8193)
                    if len(raw_error)<=8192:
                        try:
                            problem=json.loads(raw_error,object_pairs_hook=unique)
                            if (isinstance(problem,dict) and set(problem)=={'error','code'}
                                    and problem['error']=='Collector access unavailable'
                                    and problem['code']=='ACCESS_NOT_CONFIGURED'):
                                raise AccessDenied('ACCESS_NOT_CONFIGURED')
                        except (ValueError,TypeError,UnicodeError,RecursionError):
                            pass
                # http.client never follows redirects; no other origin contacted.
                raise AccessDenied('ACCESS_UNAVAILABLE' if reply.status == 503 else
                                   'ACCESS_NOT_CONFIGURED' if path == PREFIX+'config' and reply.status == 404 else 'ACCESS_REQUIRED')
            raw = reply.read(limit + 1)
            if len(raw) > limit:
                raise AccessDenied('INVALID_ACCESS_RESPONSE')
            return OnlineResponse(reply.status, OFFICIAL_ORIGIN + path, raw)
        except AccessDenied:
            raise
        except Exception:
            raise AccessDenied('ACCESS_UNAVAILABLE') from None
        finally:
            connection.close()


class DeviceMetadata:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else user_settings_directory()
        self.path = self.directory / 'device.json'
        self._settings = LocalSettings(self.directory)

    def read(self):
        try:
            with self.path.open('rb') as file:
                raw = file.read(2049)
        except FileNotFoundError:
            return None
        try:
            if len(raw) > 2048:
                raise ValueError()
            value = json.loads(raw, object_pairs_hook=unique)
            fields = {'version', 'state', 'deviceId', 'keyThumbprint', 'provider'}
            if value.get('state') in {'deletePending', 'revokedLocally'}:
                fields.add('serverRevoked')
                if type(value.get('serverRevoked')) is not bool:
                    raise ValueError()
            if (set(value) != fields
                    or type(value['version']) is not int or value['version'] != 1
                    or value['state'] not in {'active', 'unpaired', 'deletePending', 'revokedLocally'}
                    or value['provider'] not in {TPM_PROVIDER, SOFTWARE_PROVIDER}
                    or not isinstance(value['keyThumbprint'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', value['keyThumbprint'])):
                raise ValueError()
            if value['state'] == 'unpaired' or value['state'] == 'deletePending' and value['deviceId'] is None:
                if value['deviceId'] is not None:
                    raise ValueError()
            elif str(uuid.UUID(value['deviceId'])) != value['deviceId']:
                raise ValueError()
            return value
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise AccessDenied('DEVICE_STATE_INVALID') from None

    def save(self, value):
        raw = compact(value)
        with self._settings._process_lock():
            handle, name = tempfile.mkstemp(prefix='.device-', suffix='.tmp', dir=self.directory)
            temporary = Path(name)
            try:
                with os.fdopen(handle, 'wb') as file:
                    file.write(raw)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)

    def remove(self):
        with self._settings._process_lock():
            self.path.unlink(missing_ok=True)


def native_confirmation(software=False):
    if os.name != 'nt':
        return False
    message = ('Este computador não disponibilizou a chave no TPM. Usar explicitamente o armazenamento protegido por software do Windows?'
               if software else 'Autorizar este computador para continuar usando o Coletor sem repetir o login?\n\n'
               'A senha não será salva. Uma chave privada protegida pelo Windows ficará neste perfil. '
               'O acesso exige conexão e permissão de ADMINISTRADOR. Você poderá sair da conta no coletor.')
    return ctypes.windll.user32.MessageBoxW(None, message, 'Autorizar este computador — Coletor', 0x4 | 0x20 | 0x100) == 6


class DeviceProvider:
    def __init__(self, directory=None, *, transport=None, key_factory=WindowsDeviceKey,
                 consent=native_confirmation, browser=launch_system_browser, clock=time.time):
        self._metadata = DeviceMetadata(directory)
        self._transport = transport or OfficialTransport()
        self._key_factory, self._consent, self._browser, self._clock = key_factory, consent, browser, clock
        self._key = self._state = self._pending = None
        self._lock = threading.RLock()
        self._closed = False

    def _request(self, suffix, value=None):
        response = self._transport.request('GET' if suffix == 'config' else 'POST', PREFIX + suffix, value)
        if response.url != OFFICIAL_ORIGIN + PREFIX + suffix:
            raise AccessDenied('INVALID_ACCESS_RESPONSE')
        return response

    def _load(self):
        if self._state is None:
            self._state = self._metadata.read()
        if self._state is None:
            raise AccessDenied('ACCESS_REQUIRED')
        if self._key is None:
            key = self._key_factory(provider=self._state['provider'])
            try:
                public = key.load()
                if thumbprint(public) != self._state['keyThumbprint']:
                    raise AccessDenied('DEVICE_STATE_INVALID')
                self._key = key
            except Exception:
                key.close()
                raise AccessDenied('DEVICE_KEY_UNAVAILABLE') from None
        return self._key

    def _proof(self, purpose, request_hash=None):
        key = self._load()
        request = {'deviceId': self._state['deviceId'], 'purpose': purpose}
        if purpose == 'collector-frequency':
            if not isinstance(request_hash, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', request_hash):
                raise AccessDenied('INVALID_ACCESS_REQUEST')
            request['requestHash'] = request_hash
        elif request_hash is not None:
            raise AccessDenied('INVALID_ACCESS_REQUEST')
        value = decode(self._request('challenge', request))
        expected = {'deviceId', 'generation', 'accountKey', 'keyThumbprint', 'nonce', 'audience', 'method', 'path', 'purpose', 'issuedAt', 'expiresAt'}
        if purpose == 'collector-frequency': expected.add('requestHash')
        if (set(value) != expected or value['deviceId'] != self._state['deviceId'] or value['keyThumbprint'] != self._state['keyThumbprint']
                or value['audience'] != OFFICIAL_ORIGIN or value['method'] != 'POST' or value['purpose'] != purpose
                or value['path'] != PREFIX + ('frequency' if purpose == 'collector-frequency' else 'access' if purpose == 'collector-access' else 'revoke')
                or purpose == 'collector-frequency' and value.get('requestHash') != request_hash
                or type(value['generation']) is not int or value['generation'] < 1
                or any(type(value[n]) is not int for n in ('issuedAt', 'expiresAt'))
                or value['expiresAt'] - value['issuedAt'] != 60_000
                or value['issuedAt'] <= 0 or value['expiresAt'] <= value['issuedAt']
                or any(not isinstance(value[n], str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', value[n]) for n in ('nonce', 'accountKey'))):
            raise AccessDenied('INVALID_DEVICE_CHALLENGE')
        # The server clock is authoritative for the 60-second nonce; local wall-clock
        # skew must never reject a newly issued HTTPS challenge. Server verifies TTL.
        fields = ('deviceId', 'generation', 'accountKey', 'keyThumbprint', 'nonce', 'audience', 'method', 'path', 'purpose', 'issuedAt', 'expiresAt')
        if purpose == 'collector-frequency': fields += ('requestHash',)
        content = compact([value[n] for n in fields])
        self._device_generation = value['generation']
        return {'deviceId': value['deviceId'], 'nonce': value['nonce'], 'signature': key.sign_challenge(content)}

    def storage_binding(self):
        """Private Python consumer only; a fresh challenge supplies generation."""
        with self._lock:
            self._load()
            if not getattr(self, '_device_generation', None):
                raise AccessDenied('ACCESS_REQUIRED')
            return self._state['deviceId'], self._device_generation

    def frequency_request(self, payload):
        with self._lock:
            if self._closed or not isinstance(payload, dict):
                raise AccessDenied('ACCESS_REQUIRED')
            raw = canonical_frequency(payload)
            if len(raw) > FREQUENCY_BYTES - 1024:
                raise FrequencyError('invalid-request')
            request_hash = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode('ascii').rstrip('=')
            proof = self._proof('collector-frequency', request_hash)
            response = self._request('frequency', {'proof': proof, 'payload': payload})
            try:
                if not isinstance(response.body, bytes) or len(response.body) > FREQUENCY_BYTES:
                    raise ValueError()
                value = json.loads(response.body, object_pairs_hook=unique)
                if not isinstance(value, dict) or value.get('contractVersion') != 2:
                    raise ValueError()
                if response.status != 200:
                    code = value.get('state')
                    raise FrequencyError(code if code in FREQUENCY_ERRORS else 'unavailable')
                if value.get('state') not in {'ready', 'committed'}:
                    raise ValueError()
                return value
            except FrequencyError:
                raise
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise FrequencyError('unavailable') from None

    def public_status(self):
        with self._lock:
            return {'pairingCode': self._pending['displayCode']} if self._pending else {}

    def verify_online(self):
        with self._lock:
            if self._closed:
                raise AccessDenied('ACCESS_REQUIRED')
            if self._state is None:
                self._state = self._metadata.read()
            if self._state and self._state['state'] in {'deletePending', 'revokedLocally'}:
                # Status polling must be read-only for a checkpointed device.
                # Only explicit login/logout, protected by DesktopApi's queue
                # preflight, may resume the previously authorized removal.
                raise AccessDenied('ACCESS_CLEANUP_PENDING' if self._state['state'] == 'deletePending'
                                   else 'SERVER_REVOCATION_PENDING')
            if self._pending:
                result = decode(self._request('pairings/poll', {n: self._pending[n] for n in ('id', 'pollToken')}))
                if set(result) == {'contractVersion', 'state', 'deviceId'} and result['contractVersion'] == 1 and result['state'] == 'completed':
                    try:
                        device_id = str(uuid.UUID(result['deviceId']))
                    except (ValueError, TypeError, AttributeError):
                        raise AccessDenied('INVALID_ACCESS_RESPONSE') from None
                    self._state = {**self._state, 'state': 'active', 'deviceId': device_id}
                    self._metadata.save(self._state)
                    if decode(self._request('pairings/claim', {n: self._pending[n] for n in ('id', 'pollToken')})) != {'claimed': True}:
                        raise AccessDenied('PAIRING_PENDING')
                    self._pending = None
                elif set(result) == {'contractVersion', 'state'} and result['contractVersion'] == 1 and result['state'] in {'pending', 'confirmed', 'exchanging'}:
                    raise AccessDenied('PAIRING_PENDING')
                else:
                    self._pending = None
                    raise AccessDenied('ACCESS_REQUIRED')
            self._load()
            if self._state['state'] != 'active':
                raise AccessDenied('ACCESS_REQUIRED')
            return self._request('access', self._proof('collector-access'))

    def open_official_login(self):
        with self._lock:
            if self._pending:
                # A failed browser dispatch must not strand an already-created
                # pairing or force device logout/key removal. Reopen the same
                # validated official URL, with no new consent or private data
                # exposed to JavaScript. Discard expired/rejected requests only
                # after the server's own poll says they are no longer pending.
                try:
                    status = decode(self._request('pairings/poll', {
                        n: self._pending[n] for n in ('id', 'pollToken')}))
                except AccessDenied as error:
                    # The live service returns 403 for an expired/retired
                    # pairing instead of an explicit expired state. Only this
                    # explicit login action may start afresh; outages retain
                    # the request, and the new pairing still needs browser auth.
                    if error.code != 'ACCESS_REQUIRED':
                        raise
                    status = None
                if (status is not None and set(status) == {'contractVersion', 'state'}
                        and status['contractVersion'] == 1
                        and status['state'] in {'pending', 'confirmed', 'exchanging'}):
                    url = (OFFICIAL_ORIGIN + '/frequency-collector/connect?pairing='
                           + self._pending['id'])
                    if not self._browser(url, new=2):
                        raise AccessDenied('LOGIN_UNAVAILABLE')
                    return
                if (status is not None and set(status) == {'contractVersion', 'state', 'deviceId'}
                        and status['contractVersion'] == 1
                        and status['state'] == 'completed'):
                    self.verify_online()  # Claim once, without issuing a new key.
                    return
                if status is not None and (set(status) != {'contractVersion', 'state'}
                        or status['contractVersion'] != 1
                        or status['state'] not in {'expired', 'cancelled', 'denied'}):
                    raise AccessDenied('INVALID_ACCESS_RESPONSE')
                self._pending = None
            ready = decode(self._request('config'))
            if set(ready) != {'contractVersion', 'ready', 'serverTime'} or ready['contractVersion'] != 1 or ready['ready'] is not True:
                raise AccessDenied('ACCESS_NOT_CONFIGURED')
            if not self._consent():
                raise AccessDenied('DEVICE_ACTIVATION_CANCELLED')
            # Fetch current server time after a potentially long human decision.
            ready = decode(self._request('config'))
            if set(ready) != {'contractVersion', 'ready', 'serverTime'} or ready['ready'] is not True or type(ready['serverTime']) is not int:
                raise AccessDenied('ACCESS_NOT_CONFIGURED')
            self._state = self._metadata.read()
            if self._state:
                if self._state['state'] in {'deletePending', 'revokedLocally'}:
                    # A previous *explicit* removal already checkpointed this
                    # device's deletion. Resume it instead of trapping login
                    # forever. DesktopApi has checked the protected queue before
                    # allowing this path. An unconfirmed server revocation or
                    # a Windows key failure must still fail closed.
                    self.close()
                    self._state = self._metadata.read()
                    if self._state is not None:
                        raise AccessDenied('ACCESS_CLEANUP_PENDING')
            if self._state:
                public = self._load().public_jwk()
                if self._state['state'] == 'active':
                    # An earlier revocation can have reached the server even
                    # when its acknowledgement was lost. Never assume success:
                    # confirm the exact old device/key on the official server.
                    try:
                        revoked = decode(self._request('revoke', self._proof('collector-revoke'))) == {'revoked': True}
                    except AccessDenied:
                        revoked = False
                    if not revoked:
                        status = decode(self._request('device-status', {
                            'deviceId': self._state['deviceId'],
                            'keyThumbprint': self._state['keyThumbprint']}))
                        if status != {'revoked': True}:
                            raise AccessDenied('SERVER_REVOCATION_PENDING')
            else:
                provider = TPM_PROVIDER
                key = self._key_factory(provider=provider)
                try:
                    try:
                        public = key.load()
                    except DeviceKeyError:
                        public = key.create(activation_authorized=True)
                except DeviceKeyError:
                    key.close()
                    if not self._consent(software=True):
                        raise AccessDenied('DEVICE_KEY_UNAVAILABLE') from None
                    provider = SOFTWARE_PROVIDER
                    key = self._key_factory(provider=provider)
                    public = key.create(activation_authorized=True)
                self._key = key
                self._state = {'version': 1, 'state': 'unpaired', 'deviceId': None, 'keyThumbprint': thumbprint(public), 'provider': provider}
            self._state = {**self._state, 'state': 'unpaired', 'deviceId': None}
            self._metadata.save(self._state)
            pair_id, nonce, issued = str(uuid.uuid4()), secrets.token_urlsafe(32), ready['serverTime']
            body = compact([pair_id, thumbprint(public), nonce, OFFICIAL_ORIGIN, 'POST', PREFIX+'pairings', 'collector-pairing', issued, issued+120_000])
            request = {'id': pair_id, 'publicKey': public, 'nonce': nonce, 'issuedAt': issued, 'expiresAt': issued+120_000,
                       'signature': self._key.sign_challenge(body)}
            result = decode(self._request('pairings', request))
            expected_url = OFFICIAL_ORIGIN + '/frequency-collector/connect?pairing=' + pair_id
            if (set(result) != {'contractVersion', 'id', 'pollToken', 'displayCode', 'browserUrl'} or result['contractVersion'] != 1
                    or result['id'] != pair_id or result['browserUrl'] != expected_url
                    or not isinstance(result['pollToken'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', result['pollToken'])
                    or not isinstance(result['displayCode'], str) or not re.fullmatch(r'[0-9]{6}', result['displayCode'])):
                raise AccessDenied('INVALID_ACCESS_RESPONSE')
            self._pending = {n: result[n] for n in ('id', 'pollToken', 'displayCode')}
            self._closed = False
            if not self._browser(expected_url, new=2):
                raise AccessDenied('LOGIN_UNAVAILABLE')

    def _delete_local(self):
        key = self._key
        if key is None:
            key = self._key_factory(provider=self._state['provider'])
            try:
                public = key.load()
                if thumbprint(public) != self._state['keyThumbprint']:
                    raise AccessDenied('DEVICE_STATE_INVALID')
            except DeviceKeyError as error:
                key.close()
                if error.code != 'DEVICE_KEY_MISSING':
                    raise AccessDenied('ACCESS_CLEANUP_PENDING') from None
                key = None  # Checkpointed deletion is idempotent; no generic-error fallback.
        if key is not None:
            if thumbprint(key.public_jwk()) != self._state['keyThumbprint']:
                raise AccessDenied('DEVICE_STATE_INVALID')
            try:
                key.forget(removal_authorized=True)
            except DeviceKeyError:
                raise AccessDenied('ACCESS_CLEANUP_PENDING') from None
        self._key = None
        if self._state['serverRevoked'] or self._state['deviceId'] is None:
            self._metadata.remove()
            self._state = None
        else:
            self._state = {**self._state, 'state': 'revokedLocally'}
            self._metadata.save(self._state)
            raise AccessDenied('SERVER_REVOCATION_PENDING')

    def removal_status(self):
        """Read only public cleanup metadata; never open/create a key or contact a service."""
        with self._lock:
            state = self._metadata.read()
            return {} if state is None else {name: state[name] for name in ('state', 'deviceId')}

    def close(self):
        with self._lock:
            self._closed = True
            if self._state is None:
                self._state = self._metadata.read()
            if self._state is None:
                return
            if self._state['state'] == 'deletePending':
                self._delete_local()
                return
            if self._state['state'] == 'revokedLocally':
                result = decode(self._request('device-status', {'deviceId': self._state['deviceId'], 'keyThumbprint': self._state['keyThumbprint']}))
                if set(result) == {'revoked'} and result['revoked'] is True:
                    self._metadata.remove()
                    self._state = None
                    return
                self._browser(OFFICIAL_ORIGIN+'/frequency-collector/revoke?device='+self._state['deviceId'], new=2)
                raise AccessDenied('SERVER_REVOCATION_PENDING')
            confirmed = self._state['deviceId'] is None
            if self._pending:
                pending, self._pending = self._pending, None
                try:
                    result = decode(self._request('pairings/cancel', {n: pending[n] for n in ('id', 'pollToken')}))
                    confirmed = set(result) == {'cancelled'} and result['cancelled'] is True
                except Exception:
                    pass
            if self._state['deviceId'] is not None:
                try:
                    result = decode(self._request('revoke', self._proof('collector-revoke')))
                    confirmed = set(result) == {'revoked'} and result['revoked'] is True
                except Exception:
                    pass  # Offline logout must still delete the local key.
            self._state = {**self._state, 'state': 'deletePending', 'serverRevoked': confirmed}
            self._metadata.save(self._state)  # Durable checkpoint precedes NCryptDeleteKey.
            self._delete_local()

    def release(self):
        with self._lock:
            # Closing the program retains its authorized device. Pending polling
            # secrets never persist; a pending row expires in ten minutes.
            if self._key is not None:
                self._key.close()
                self._key = None
            if self._pending:
                try:
                    if decode(self._request('pairings/cancel', {n: self._pending[n] for n in ('id', 'pollToken')})) == {'cancelled': True} and self._state:
                        self._state = {**self._state, 'state': 'unpaired', 'deviceId': None}
                        self._metadata.save(self._state)
                except Exception:
                    pass  # An unclaimed device cannot authorize an operation.
            self._pending = None
