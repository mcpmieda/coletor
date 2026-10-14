"""Native CNG interoperability QA. Only anonymous Software KSP keys, no account.

Peer is a bundled snapshot of the actual backend proof parsers/verifiers. It
receives only public key/challenge/signature through stdin. No service URL is
contacted and no browser/human-activation dialog is opened by this fixture.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from coletor.device_provider import DeviceProvider, compact, canonical_frequency, PREFIX, OFFICIAL_ORIGIN, thumbprint
from coletor.institutional_access import OnlineResponse, validate_authorization
from coletor.windows_device_key import NativeCng, WindowsDeviceKey, DeviceKeyError, SOFTWARE_PROVIDER


class AnonymousCrypto(NativeCng):
    def __init__(self):
        super().__init__()
        self.created = self.released = 0

    def open(self, provider):
        raise DeviceKeyError('DEVICE_KEY_MISSING')  # Never inspect a user's real named key.

    def create(self, provider):
        handle = ctypes.c_size_t()
        self._check(self.dll.NCryptCreatePersistedKey(provider, ctypes.byref(handle), 'ECDSA_P256', None, 0, 0))
        self.created += 1
        return handle.value

    def delete(self, key):
        self.free(key)  # Anonymous fixture: freeing destroys it; not proof of persisted deletion.
        self.released += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--peer', type=Path, default=Path(__file__).resolve().parents[1]/'fixtures/collector-peer-fixture.mjs')
    parser.add_argument('--output', type=Path, default=Path('artifacts/device-auth/provider.json'))
    args = parser.parse_args()
    peer, node = args.peer.resolve(), shutil.which('node')
    if not node or not peer.is_file():
        raise RuntimeError('fixture-peer-unavailable')
    provenance = json.loads(peer.with_name('collector-peer-provenance.json').read_text(encoding='utf-8'))
    if hashlib.sha256(peer.read_bytes()).hexdigest() != provenance['bundle_sha256']:
        raise RuntimeError('fixture-peer-integrity-failed')
    def call(value):
        result = subprocess.run([node, str(peer)], input=compact(value), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False)
        if result.returncode != 0:
            raise RuntimeError('fixture-proof-denied')
        return json.loads(result.stdout)
    device = '11111111-1111-4111-8111-111111111111'
    crypto = AnonymousCrypto()
    consent_calls, validations = [], []
    class Transport:
        public = challenge = record = None
        def request(self, method, path, value=None):
            suffix, now = path.removeprefix(PREFIX), int(time.time()*1000)
            if suffix == 'config':
                body = {'contractVersion': 1, 'ready': True, 'serverTime': now}
            elif suffix == 'pairings':
                assert call({'operation': 'pairing', 'body': value, 'now': now}) == {'valid': True}
                self.public = value['publicKey']
                self.record = {'deviceId': device, 'generation': 1, 'tenantId': '22222222-2222-4222-8222-222222222222',
                               'actorId': '33333333-3333-4333-8333-333333333333', 'keyThumbprint': thumbprint(self.public),
                               'publicKey': self.public, 'revokedAt': None}
                validations.append('native-cng-pairing-verified-by-backend')
                body = {'contractVersion': 1, 'id': value['id'], 'pollToken': 'p'*43, 'displayCode': '123456',
                        'browserUrl': OFFICIAL_ORIGIN+'/frequency-collector/connect?pairing='+value['id']}
            elif suffix == 'pairings/poll':
                body = {'contractVersion': 1, 'state': 'completed', 'deviceId': device}
            elif suffix == 'pairings/claim':
                body = {'claimed': True}
            elif suffix == 'challenge':
                request = {'operation': 'challenge', 'record': self.record, 'now': now, 'purpose': value['purpose']}
                if 'requestHash' in value: request['requestHash'] = value['requestHash']
                self.challenge = call(request)
                body = self.challenge
            elif suffix == 'frequency':
                import base64
                proof = value['proof']
                assert call({'operation': 'verify', 'record': self.record, 'challenge': self.challenge,
                             'signature': proof['signature'], 'now': now, 'purpose': 'collector-frequency'}) == {'valid': True}
                request_hash = base64.urlsafe_b64encode(hashlib.sha256(canonical_frequency(value['payload'])).digest()).decode().rstrip('=')
                assert request_hash == self.challenge['requestHash']
                altered = {**value['payload'], 'academicYear': 2025}
                altered_hash = base64.urlsafe_b64encode(hashlib.sha256(canonical_frequency(altered)).digest()).decode().rstrip('=')
                denied = False
                try:
                    denied = call({'operation': 'verify', 'record': self.record,
                        'challenge': {**self.challenge, 'requestHash': altered_hash},
                        'signature': proof['signature'], 'now': now, 'purpose': 'collector-frequency'}) != {'valid': True}
                except RuntimeError: denied = True
                assert denied
                validations.extend(['native-cng-frequency-verified-by-backend', 'native-cng-frequency-altered-payload-rejected'])
                body = {'contractVersion': 2, 'state': 'ready', 'academicYear': 2026}
            elif suffix in {'access', 'revoke'}:
                purpose = 'collector-access' if suffix == 'access' else 'collector-revoke'
                assert call({'operation': 'verify', 'record': self.record, 'challenge': self.challenge,
                             'signature': value['signature'], 'now': now, 'purpose': purpose}) == {'valid': True}
                validations.append('native-cng-'+suffix+'-verified-by-backend')
                if suffix == 'revoke':
                    body = {'revoked': True}
                else:
                    stamp = lambda milliseconds: datetime.fromtimestamp(milliseconds/1000, timezone.utc).isoformat()
                    body = {'contractVersion': 2, 'authenticated': True, 'authorized': True, 'capability': 'frequency.collector.use',
                            'identityKey': 'anonymous-cng-synthetic-account', 'checkedAt': stamp(now), 'expiresAt': stamp(now+60_000),
                            'directoryCheckedAt': stamp(now), 'directoryValidUntil': stamp(now+300_000), 'revocationChecked': True}
            else:
                raise RuntimeError('fixture-unexpected-operation')
            return OnlineResponse(200, OFFICIAL_ORIGIN+path, compact(body))
    with tempfile.TemporaryDirectory(prefix='coletor-anonymous-provider-') as temporary:
        def key_factory(**_):
            return WindowsDeviceKey(crypto=crypto, provider=SOFTWARE_PROVIDER)
        def consent(**kw):
            consent_calls.append(kw)
            return True  # Fixture, no human consent or production activation is asserted.
        provider = DeviceProvider(temporary, transport=Transport(), key_factory=key_factory, consent=consent,
                                  browser=lambda *_a, **_kw: True)
        try:
            provider.open_official_login()
            validate_authorization(provider.verify_online(), time.time())
            provider.frequency_request({'operation': 'status', 'academicYear': 2026})
            provider.close()
            assert not (Path(temporary)/'device.json').exists()
            assert crypto.created == crypto.released == 1
        finally:
            provider.release()
    result = {'passed': True, 'synthetic_backend': True, 'real_network': False, 'real_accounts': False,
              'named_keys_created': 0, 'anonymous_keys_created': crypto.created, 'anonymous_keys_released': crypto.released,
              'persistent_key_deletion_proven': False, 'human_activation_proven': False, 'checks': validations}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
