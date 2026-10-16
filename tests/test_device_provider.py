import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from datetime import datetime, timezone

from coletor.device_provider import DeviceProvider, OfficialTransport, PREFIX, compact, thumbprint
from coletor.institutional_access import AccessDenied, OnlineResponse, OFFICIAL_ORIGIN, validate_authorization
from coletor.windows_device_key import WindowsDeviceKey, TPM_PROVIDER, SOFTWARE_PROVIDER, DeviceKeyError
from test_windows_device_key import FakeCrypto

NOW = 1791930000
DEVICE = '11111111-1111-4111-8111-111111111111'


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class SyntheticTransport:
    def __init__(self):
        self.calls = []
        self.public = None
        self.completed = False
        self.claimed = False
        self.revoked = False
        self.change = lambda suffix, value: value

    def request(self, method, path, value=None):
        suffix = path.removeprefix(PREFIX)
        self.calls.append((method, suffix, value))
        if suffix == 'config':
            body = {'contractVersion': 1, 'ready': True, 'serverTime': NOW*1000}
        elif suffix == 'pairings':
            self.public = value['publicKey']
            body = {'contractVersion': 1, 'id': value['id'], 'pollToken': 'z'*43, 'displayCode': '123456',
                    'browserUrl': OFFICIAL_ORIGIN+'/frequency-collector/connect?pairing='+value['id']}
        elif suffix == 'pairings/poll':
            body = {'contractVersion': 1, 'state': 'completed', 'deviceId': DEVICE} if self.completed else {'contractVersion': 1, 'state': 'pending'}
        elif suffix == 'pairings/claim':
            self.claimed = True
            body = {'claimed': True}
        elif suffix == 'pairings/cancel':
            body = {'cancelled': True}
        elif suffix == 'challenge':
            purpose = value['purpose']
            if purpose == 'collector-access' and not self.claimed:
                raise AccessDenied('ACCESS_REQUIRED')
            body = {'deviceId': value['deviceId'], 'generation': 1, 'accountKey': 'a'*43,
                    'keyThumbprint': thumbprint(self.public), 'nonce': 'n'*43, 'audience': OFFICIAL_ORIGIN, 'method': 'POST',
                    'path': PREFIX+('access' if purpose == 'collector-access' else 'revoke'), 'purpose': purpose,
                    'issuedAt': NOW*1000, 'expiresAt': NOW*1000+60_000}
        elif suffix == 'revoke':
            self.revoked = True
            body = {'revoked': True}
        elif suffix == 'device-status':
            body = {'revoked': self.revoked}
        elif suffix == 'access':
            body = {'contractVersion': 2, 'authenticated': True, 'authorized': True, 'capability': 'frequency.collector.use',
                    'identityKey': DEVICE+':synthetic-account', 'checkedAt': stamp(NOW), 'expiresAt': stamp(NOW+60),
                    'directoryCheckedAt': stamp(NOW), 'directoryValidUntil': stamp(NOW+300), 'revocationChecked': True}
        else:
            raise AssertionError('unexpected-synthetic-path')
        body = self.change(suffix, body)
        return OnlineResponse(200, OFFICIAL_ORIGIN+path, compact(body))


class DeviceProviderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)/'isolated-device'
        self.crypto, self.transport, self.browser = FakeCrypto(), SyntheticTransport(), Mock(return_value=True)
        self.factory = Mock(side_effect=lambda **kw: WindowsDeviceKey(crypto=self.crypto, **kw))
        self.consent = Mock(return_value=True)
        self.provider = self.make_provider()

    def make_provider(self):
        return DeviceProvider(self.root, transport=self.transport, key_factory=self.factory,
                              consent=self.consent, browser=self.browser, clock=lambda: NOW)

    def tearDown(self):
        self.provider.release()
        self.temporary.cleanup()

    def activate(self):
        self.provider.open_official_login()
        self.transport.completed = True
        return self.provider.verify_online()

    def test_frequency_challenge_binds_full_utf8_payload_and_legacy_bytes_remain_unchanged(self):
        import base64
        import hashlib
        from coletor.device_provider import canonical_frequency
        self.activate()
        request = self.transport.request
        captured = {}
        def frequency(method, path, value=None):
            if path == PREFIX + 'challenge' and value['purpose'] == 'collector-frequency':
                body = {'deviceId': DEVICE, 'generation': 1, 'accountKey': 'a'*43, 'keyThumbprint': self.provider._state['keyThumbprint'],
                        'nonce': 'n'*43, 'audience': OFFICIAL_ORIGIN, 'method': 'POST', 'path': PREFIX+'frequency',
                        'purpose': 'collector-frequency', 'issuedAt': NOW*1000, 'expiresAt': NOW*1000+60_000,
                        'requestHash': value['requestHash']}
                captured['challenge'] = body
                return OnlineResponse(200, OFFICIAL_ORIGIN+path, compact(body))
            if path == PREFIX+'frequency':
                captured['payload'] = value['payload']
                return OnlineResponse(200, OFFICIAL_ORIGIN+path, compact({'contractVersion': 2, 'state': 'ready'}))
            return request(method, path, value)
        self.transport.request = frequency
        payload = {'operation': 'status', 'academicYear': 2026, 'synthetic': 'ação'}
        self.provider.frequency_request(payload)
        self.assertIn('ação'.encode('utf-8'), canonical_frequency(payload))
        wanted = base64.urlsafe_b64encode(hashlib.sha256(canonical_frequency(payload)).digest()).decode().rstrip('=')
        self.assertEqual(captured['challenge']['requestHash'], wanted)
        fields = ('deviceId','generation','accountKey','keyThumbprint','nonce','audience','method','path','purpose','issuedAt','expiresAt','requestHash')
        content = compact([captured['challenge'][n] for n in fields])
        digest = hashlib.sha256(b'Ecossistema.Coletor.DeviceProof.v1\0' + content).digest()
        self.assertIn(('sign', digest), self.crypto.calls)
        self.assertEqual(captured['payload'], payload)
        self.assertNotIn('requestHash', (self.root/'device.json').read_text())

    def test_new_server_challenge_does_not_depend_on_windows_wall_clock(self):
        # Server proves nonce lifetime in the database. An unsynchronised PC
        # must not reject a fresh server-issued challenge before signing it.
        self.activate()
        self.provider._clock = lambda: NOW - 90
        reply = self.provider.verify_online()
        self.assertEqual(reply.status, 200)

    def test_frequency_challenge_cannot_add_unbound_purpose_fields_to_legacy_proof(self):
        self.activate()
        self.transport.change = lambda suffix, body: {**body, 'requestHash': 'x'*43} if suffix == 'challenge' else body
        with self.assertRaises(AccessDenied): self.provider.verify_online()

    def test_construction_and_unpaired_status_create_nothing_and_contact_no_service(self):
        self.assertFalse(self.root.exists())
        with self.assertRaises(AccessDenied):
            self.provider.verify_online()
        self.assertFalse(self.root.exists())
        self.assertEqual(self.crypto.calls, [])
        self.assertEqual(self.transport.calls, [])

    def test_configuration_failure_precedes_human_decision_and_key_creation(self):
        self.transport.request = Mock(side_effect=AccessDenied('ACCESS_NOT_CONFIGURED'))
        with self.assertRaises(AccessDenied):
            self.provider.open_official_login()
        self.consent.assert_not_called()
        self.factory.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_human_denial_never_creates_a_credential(self):
        self.consent.return_value = False
        with self.assertRaises(AccessDenied):
            self.provider.open_official_login()
        self.factory.assert_not_called()
        self.assertEqual([p[1] for p in self.transport.calls], ['config'])
        self.assertFalse(self.root.exists())

    def test_pairing_signature_is_bound_and_only_nonsecret_metadata_persists(self):
        self.provider.open_official_login()
        self.assertEqual(self.provider.public_status(), {'pairingCode': '123456'})
        self.browser.assert_called_once()
        sent = next(p[2] for p in self.transport.calls if p[1] == 'pairings')
        self.assertEqual(set(sent), {'id', 'publicKey', 'nonce', 'issuedAt', 'expiresAt', 'signature'})
        self.assertEqual(sent['expiresAt']-sent['issuedAt'], 120_000)
        self.assertNotIn('d', sent['publicKey'])
        disk = (self.root/'device.json').read_text()
        self.assertNotIn('z'*43, disk)
        self.assertNotIn('signature', disk)
        self.assertNotIn('password', disk)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['device.json', 'settings.lock'])
        with self.assertRaises(AccessDenied):
            self.provider.verify_online()

    def test_complete_pairing_claims_after_metadata_save_and_renews_without_browser_or_new_key(self):
        validate_authorization(self.activate(), NOW)
        self.assertEqual(self.provider.public_status(), {})
        self.provider.release()
        restarted = self.make_provider()
        try:
            validate_authorization(restarted.verify_online(), NOW)
            validate_authorization(restarted.verify_online(), NOW)
            self.assertEqual(sum(c[0] == 'create' for c in self.crypto.calls), 1)
            self.browser.assert_called_once()
            self.assertEqual(json.loads((self.root/'device.json').read_text())['deviceId'], DEVICE)
        finally:
            restarted.release()

    def test_cancelling_pending_pairing_deletes_key_and_cannot_authorize(self):
        self.provider.open_official_login()
        self.provider.close()
        self.assertEqual(sum(c[1] == 'pairings/cancel' for c in self.transport.calls), 1)
        self.assertFalse(self.crypto.exists)
        self.assertFalse((self.root/'device.json').exists())
        self.assertEqual(self.provider.public_status(), {})
        with self.assertRaises(AccessDenied):
            self.provider.verify_online()
        self.assertFalse(self.transport.claimed)

    def test_closing_pending_pairing_offline_drops_secret_and_reopen_stays_denied(self):
        self.provider.open_official_login()
        original = self.transport.request
        def offline_cancel(method, path, value=None):
            if path == PREFIX+'pairings/cancel':
                raise AccessDenied('ACCESS_UNAVAILABLE')
            return original(method, path, value)
        self.transport.request = offline_cancel
        self.provider.release()
        self.assertEqual(self.provider.public_status(), {})
        self.assertNotIn('z'*43, (self.root/'device.json').read_text())
        restarted = self.make_provider()
        try:
            with self.assertRaises(AccessDenied):
                restarted.verify_online()
            self.assertFalse(self.transport.claimed)
            self.assertEqual(sum(c[0] == 'create' for c in self.crypto.calls), 1)
        finally:
            restarted.release()

    def test_unavailable_renewal_denies_then_recovers_without_new_key_or_login(self):
        self.activate()
        original = self.transport.request
        self.transport.request = Mock(side_effect=AccessDenied('ACCESS_UNAVAILABLE'))
        with self.assertRaises(AccessDenied):
            self.provider.verify_online()
        self.assertTrue(self.crypto.exists)
        self.browser.assert_called_once()
        self.transport.request = original
        validate_authorization(self.provider.verify_online(), NOW)
        self.assertEqual(sum(c[0] == 'create' for c in self.crypto.calls), 1)
        self.browser.assert_called_once()

    def test_refuses_swapped_route_key_time_nonce_and_extra_challenge_fields(self):
        self.activate()
        for changes in [{'path': PREFIX+'revoke'}, {'purpose': 'collector-revoke'}, {'keyThumbprint': 'x'*43},
                        {'deviceId': '22222222-2222-4222-8222-222222222222'}, {'expiresAt': NOW*1000},
                        {'nonce': 'bad'}, {'refresh_token': 'PRIVATE_SENTINEL'}]:
            self.transport.change = lambda suffix, value, changes=changes: {**value, **changes} if suffix == 'challenge' else value
            count = sum(p[1] == 'access' for p in self.transport.calls)
            with self.assertRaises(AccessDenied):
                self.provider.verify_online()
            self.assertEqual(sum(p[1] == 'access' for p in self.transport.calls), count)

    def test_server_cannot_redirect_the_browser_to_a_different_origin(self):
        self.transport.change = lambda suffix, value: {**value, 'browserUrl': 'https://other.invalid'} if suffix == 'pairings' else value
        with self.assertRaises(AccessDenied):
            self.provider.open_official_login()
        self.browser.assert_not_called()

    def test_software_provider_requires_its_own_explicit_human_decision(self):
        original = self.factory.side_effect
        def factory(**kw):
            if kw['provider'] == TPM_PROVIDER:
                key = Mock()
                key.load.side_effect = DeviceKeyError()
                key.create.side_effect = DeviceKeyError()
                return key
            return original(**kw)
        self.factory.side_effect = factory
        self.consent.side_effect = [True, False]
        with self.assertRaises(AccessDenied):
            self.provider.open_official_login()
        self.assertFalse(self.crypto.exists)
        self.consent.assert_called_with(software=True)
        self.consent.side_effect = [True, True]
        self.provider.open_official_login()
        self.assertEqual(self.provider._state['provider'], SOFTWARE_PROVIDER)

    def test_logout_revokes_then_deletes_only_its_key_and_metadata(self):
        self.activate()
        (self.root/'unrelated.txt').write_text('UNCHANGED')
        self.provider.close()
        self.assertFalse(self.crypto.exists)
        self.assertFalse((self.root/'device.json').exists())
        self.assertEqual((self.root/'unrelated.txt').read_text(), 'UNCHANGED')
        self.assertIn('revoke', [p[1] for p in self.transport.calls])
        with self.assertRaises(AccessDenied):
            self.provider.verify_online()

    def test_offline_logout_deletes_key_and_requires_server_completion_without_renewal(self):
        self.activate()
        original = self.transport.request
        self.transport.request = lambda method, path, value=None: (_ for _ in ()).throw(AccessDenied('ACCESS_UNAVAILABLE')) if path.endswith('/revoke') else original(method, path, value)
        with self.assertRaises(AccessDenied):
            self.provider.close()
        self.assertFalse(self.crypto.exists)
        self.assertEqual(json.loads((self.root/'device.json').read_text())['state'], 'revokedLocally')
        with self.assertRaises(AccessDenied):
            self.provider.verify_online()
        self.transport.request = original
        restarted = self.make_provider()
        with self.assertRaises(AccessDenied):
            restarted.verify_online()
        self.assertTrue(self.browser.call_args.args[0].startswith(OFFICIAL_ORIGIN+'/frequency-collector/revoke?device='))
        self.transport.revoked = True  # Synthetic owner-only browser confirmation.
        restarted.close()
        self.assertFalse(self.crypto.exists)
        self.assertFalse((self.root/'device.json').exists())

    def test_restart_after_metadata_save_before_claim_can_revoke_and_prepare_a_new_pairing(self):
        self.provider.open_official_login()
        self.transport.completed = True
        original = self.transport.request
        self.transport.request = lambda method, path, value=None: (_ for _ in ()).throw(AccessDenied('ACCESS_UNAVAILABLE')) if path.endswith('/claim') else original(method, path, value)
        with self.assertRaises(AccessDenied):
            self.provider.verify_online()
        self.assertFalse(self.transport.claimed)
        self.assertEqual(json.loads((self.root/'device.json').read_text())['state'], 'active')
        # Simulate process loss: release only its handles, without graceful cancellation.
        self.provider._key.close()
        self.provider._key = None
        self.provider._pending = None
        self.transport.request = original
        restarted = self.make_provider()
        with self.assertRaises(AccessDenied):
            restarted.verify_online()
        restarted.open_official_login()
        self.assertTrue(self.transport.revoked)
        self.assertIsNotNone(restarted._pending)
        restarted.release()

    def test_metadata_unlink_failure_after_key_delete_is_recoverable_on_retry_and_restart(self):
        self.activate()
        original = self.provider._metadata.remove
        self.provider._metadata.remove = Mock(side_effect=PermissionError('PRIVATE_PATH'))
        with self.assertRaises(PermissionError):
            self.provider.close()
        self.assertFalse(self.crypto.exists)
        self.assertEqual(json.loads((self.root/'device.json').read_text())['state'], 'deletePending')
        self.provider._metadata.remove = original
        restarted = self.make_provider()
        restarted.close()
        self.assertFalse((self.root/'device.json').exists())
        restarted.release()

    def test_policy_failure_is_never_treated_as_an_already_deleted_key(self):
        self.activate()
        self.provider._key.close()
        self.provider._key = None
        state = {**self.provider._state, 'state': 'deletePending', 'serverRevoked': True}
        self.provider._state = state
        self.provider._metadata.save(state)
        self.crypto.properties['Export Policy'] = b'\x01\x00\x00\x00'
        with self.assertRaises(AccessDenied):
            self.provider.close()
        self.assertTrue(self.crypto.exists)
        self.assertTrue((self.root/'device.json').exists())

    def test_malformed_saved_state_cannot_authorize_or_echo_private_fields(self):
        self.root.mkdir()
        path = self.root/'device.json'
        path.write_text('{"password":"PRIVATE_SENTINEL"}')
        with self.assertRaises(AccessDenied) as caught:
            self.provider.verify_online()
        self.assertNotIn('PRIVATE_SENTINEL', str(caught.exception))
        self.assertEqual(path.read_text(), '{"password":"PRIVATE_SENTINEL"}')
        self.assertEqual(self.crypto.calls, [])


class TransportTests(unittest.TestCase):
    def connection(self, status=200, raw=b'{}', headers=None):
        reply = Mock(status=status)
        h = {'Content-Type': 'application/json', **(headers or {})}
        reply.getheader.side_effect = h.get
        reply.read.return_value = raw
        connection = Mock()
        connection.getresponse.return_value = reply
        return connection

    def test_redirects_never_forward_proof_or_contact_a_second_destination(self):
        for status in (301, 302, 307, 308):
            connection = self.connection(status=status, headers={'Location': 'https://other.invalid'})
            transport = OfficialTransport(connection=lambda: connection)
            with self.assertRaises(AccessDenied):
                transport.request('POST', PREFIX+'access', {'signature': 'synthetic'})
            self.assertEqual(connection.request.call_count, 1)
            connection.close.assert_called_once()
            self.assertNotIn('Authorization', connection.request.call_args.kwargs['headers'])
            self.assertNotIn('Cookie', connection.request.call_args.kwargs['headers'])

    def test_http_503_is_transient_and_not_a_revocation_receipt(self):
        for path in ('config', 'challenge', 'access'):
            connection = self.connection(status=503)
            with self.assertRaises(AccessDenied) as caught:
                OfficialTransport(connection=lambda: connection).request(
                    'GET' if path == 'config' else 'POST', PREFIX+path,
                    None if path == 'config' else {'deviceId': DEVICE})
            self.assertEqual(caught.exception.code, 'ACCESS_UNAVAILABLE')

    def test_disabled_config_503_is_specific_but_generic_503_stays_transient(self):
        exact=compact({'error':'Collector access unavailable','code':'ACCESS_NOT_CONFIGURED'})
        connection=self.connection(status=503,raw=exact)
        with self.assertRaises(AccessDenied) as caught:
            OfficialTransport(connection=lambda:connection).request('GET',PREFIX+'config')
        self.assertEqual(caught.exception.code,'ACCESS_NOT_CONFIGURED')
        for raw in [b'{}',b'<html>temporary outage</html>',
                    compact({'error':'anything','code':'ACCESS_NOT_CONFIGURED'})]:
            connection=self.connection(status=503,raw=raw)
            with self.assertRaises(AccessDenied) as denied:
                OfficialTransport(connection=lambda:connection).request('GET',PREFIX+'config')
            self.assertEqual(denied.exception.code,'ACCESS_UNAVAILABLE')

    def test_bounds_response_and_rejects_compressed_non_json_and_foreign_paths(self):
        for raw, headers in [(b'x'*8193, {}), (b'{}', {'Content-Length': '999999'}),
                             (b'{}', {'Content-Encoding': 'gzip'}), (b'{}', {'Content-Type': 'text/html'})]:
            connection = self.connection(raw=raw, headers=headers)
            with self.assertRaises(AccessDenied):
                OfficialTransport(connection=lambda: connection).request('GET', PREFIX+'config')
        connection = self.connection()
        with self.assertRaises(AccessDenied):
            OfficialTransport(connection=lambda: connection).request('POST', '/auth/callback', {})
        connection.request.assert_not_called()
