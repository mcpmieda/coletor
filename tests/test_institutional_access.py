import json
import unittest
from datetime import datetime, timezone
from coletor.institutional_access import (AccessDenied, InstitutionalAccess, OnlineResponse,
    PROPOSED_ACCESS_URL, PROPOSED_CAPABILITY, validate_authorization)

NOW = 1791930000


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def response(**changes):
    body = {"contractVersion": 2, "authenticated": True, "authorized": True,
            "capability": PROPOSED_CAPABILITY, "identityKey": "synthetic-account:1",
            "expiresAt": stamp(NOW+60), "checkedAt": stamp(NOW), "revocationChecked": True,
            "directoryCheckedAt": stamp(NOW), "directoryValidUntil": stamp(NOW+300)}
    body.update(changes)
    return OnlineResponse(200, PROPOSED_ACCESS_URL, json.dumps(body).encode())


class Provider:
    def __init__(self, values):
        self.values = iter(values)
        self.reads = 0
        self.opened = False
        self.closed = False

    def verify_online(self):
        self.reads += 1
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value

    def open_official_login(self):
        self.opened = True

    def close(self):
        self.closed = True


class InstitutionalAccessTests(unittest.TestCase):
    def test_no_provider_never_runs_command_or_claims_ready(self):
        calls = []
        gate = InstitutionalAccess(on_locked=lambda: calls.append('locked'))
        with self.assertRaises(AccessDenied):
            gate.run(lambda: calls.append('collection'))
        self.assertNotIn('collection', calls)
        self.assertEqual(gate.status()['code'], 'ACCESS_NOT_CONFIGURED')
        with self.assertRaises(AccessDenied):
            gate.open_login()

    def test_each_command_checks_online_before_and_after_without_cached_lease(self):
        provider = Provider([response()] * 4)
        gate = InstitutionalAccess(provider, clock=lambda: NOW)
        self.assertEqual(gate.run(lambda: 'preview'), 'preview')
        self.assertEqual(gate.run(lambda: 'selection'), 'selection')
        self.assertEqual(provider.reads, 4)

    def test_expired_and_stale_receipts_block_even_successful_status(self):
        for item in [response(expiresAt=stamp(NOW)), response(checkedAt=stamp(NOW-11)),
                     response(checkedAt=stamp(NOW+6)), response(expiresAt='2026-10-13T10:00:00')]:
            with self.subTest(item=item), self.assertRaises(AccessDenied):
                validate_authorization(item, NOW)

    def test_server_denial_and_offline_never_run_command(self):
        for item in [OnlineResponse(401, PROPOSED_ACCESS_URL, b'{}'),
                     OnlineResponse(403, PROPOSED_ACCESS_URL, b'{}'),
                     RuntimeError('private-cookie-value'), OnlineResponse(503, PROPOSED_ACCESS_URL, b'{}')]:
            provider = Provider([item])
            gate = InstitutionalAccess(provider, clock=lambda: NOW)
            calls = []
            with self.assertRaises(AccessDenied) as caught:
                gate.run(lambda: calls.append('work'))
            self.assertEqual(calls, [])
            self.assertNotIn('private-cookie', str(caught.exception))

    def test_expiry_or_revocation_during_read_discards_late_result(self):
        for later in [response(authorized=False), response(expiresAt=stamp(NOW))]:
            gate = InstitutionalAccess(Provider([response(), later]), clock=lambda: NOW)
            with self.assertRaises(AccessDenied):
                gate.run(lambda: {'private_preview': 'synthetic'})

    def test_identity_switch_during_read_discards_result(self):
        gate = InstitutionalAccess(Provider([response(), response(identityKey='other:1')]), clock=lambda: NOW)
        with self.assertRaises(AccessDenied):
            gate.run(lambda: 'preview')

    def test_concurrent_transient_check_does_not_revoke_inflight_valid_work(self):
        locked = []
        provider = Provider([response(), AccessDenied('ACCESS_UNAVAILABLE'), response()])
        gate = InstitutionalAccess(provider, clock=lambda: NOW,
                                   on_locked=lambda: locked.append('revoked'))
        def capture_with_heartbeat_outage():
            # A background heartbeat/status failure must not invalidate the
            # generation of a capture whose own final gate later passes.
            status = gate.status()
            self.assertEqual(status['code'], 'ACCESS_UNAVAILABLE')
            return 'synthetic-capture'
        self.assertEqual(gate.run(capture_with_heartbeat_outage), 'synthetic-capture')
        self.assertEqual(locked, [])
        self.assertEqual(provider.reads, 3)

    def test_concurrent_confirmed_denial_still_cancels_inflight_work(self):
        locked = []
        provider = Provider([response(), AccessDenied('ACCESS_REQUIRED'), response()])
        gate = InstitutionalAccess(provider, clock=lambda: NOW,
                                   on_locked=lambda: locked.append('revoked'))
        with self.assertRaises(AccessDenied):
            gate.run(lambda: gate.status())
        self.assertTrue(locked)

    def test_logout_during_operation_invalidates_generation(self):
        provider = Provider([response(), response()])
        gate = InstitutionalAccess(provider, clock=lambda: NOW)
        with self.assertRaises(AccessDenied):
            gate.run(lambda: gate.logout())
        self.assertTrue(provider.closed)

    def test_current_me_identity_is_not_collector_authorization(self):
        identity = {'authenticated': True, 'identityKey': 'synthetic:1', 'expiresAt': stamp(NOW+60),
                    'roles': ['ADMINISTRADOR'], 'capabilities': ['gradebook.persistence.admin']}
        with self.assertRaises(AccessDenied):
            validate_authorization(OnlineResponse(200, PROPOSED_ACCESS_URL, json.dumps(identity).encode()), NOW)

    def test_unverified_revocation_or_other_capability_denied(self):
        for item in [response(revocationChecked=False), response(capability='platform.modules.read'),
                     response(authenticated=1), response(contractVersion=True), response(authorized='true')]:
            with self.subTest(item=item), self.assertRaises(AccessDenied):
                validate_authorization(item, NOW)

    def test_foreign_or_redirected_response_and_large_body_denied(self):
        for item in [OnlineResponse(200, 'https://attacker.invalid/api/frequency-collector/access', response().body),
                     OnlineResponse(302, PROPOSED_ACCESS_URL, response().body),
                     OnlineResponse(200, PROPOSED_ACCESS_URL, b'x'*8193)]:
            with self.assertRaises(AccessDenied):
                validate_authorization(item, NOW)

    def test_malformed_duplicate_or_credential_fields_denied(self):
        for item in [OnlineResponse(200, PROPOSED_ACCESS_URL, b'{"authorized":true,"authorized":false}'),
                     response(password='do-not-persist'), response(identityKey='hidden\nidentity'),
                     OnlineResponse(200, PROPOSED_ACCESS_URL, b'\xff')]:
            with self.assertRaises(AccessDenied):
                validate_authorization(item, NOW)

    def test_cleanup_failure_keeps_gate_locked(self):
        def failed_cleanup():
            raise RuntimeError('private browser cleanup failed')
        provider = Provider([response(authorized=False), response()])
        gate = InstitutionalAccess(provider, clock=lambda: NOW, on_locked=failed_cleanup)
        self.assertFalse(gate.status()['authorized'])
        self.assertEqual(gate.status()['code'], 'ACCESS_CLEANUP_PENDING')
        self.assertEqual(provider.reads, 1)
        with self.assertRaises(AccessDenied):
            gate.open_login()

    def test_successful_explicit_cleanup_retry_clears_pending_but_does_not_authorize(self):
        from unittest.mock import Mock
        provider = Provider([])
        provider.close = Mock(side_effect=[RuntimeError('synthetic-transient'), None])
        gate = InstitutionalAccess(provider, clock=lambda: NOW)
        with self.assertRaises(AccessDenied):
            gate.logout()
        self.assertTrue(gate._cleanup_pending)
        gate.logout()
        self.assertFalse(gate._cleanup_pending)
        gate.open_login()
        self.assertTrue(provider.opened)

    def test_source_cleanup_failure_does_not_skip_device_revocation_and_key_deletion(self):
        from unittest.mock import Mock
        provider = Provider([])
        provider.close = Mock()
        cleanup = Mock(side_effect=RuntimeError('synthetic-temporary-cleanup'))
        gate = InstitutionalAccess(provider, clock=lambda: NOW, on_locked=cleanup)
        with self.assertRaises(AccessDenied):
            gate.logout()
        provider.close.assert_called_once()
        self.assertTrue(gate._cleanup_pending)
        self.assertEqual(gate.status()['code'], 'ACCESS_CLEANUP_PENDING')

    def test_local_check_cannot_extend_expired_directory_evidence(self):
        with self.assertRaises(AccessDenied):
            validate_authorization(response(directoryCheckedAt=stamp(NOW-301),
                directoryValidUntil=stamp(NOW-1)), NOW)

    def test_lease_cannot_outlive_directory_window(self):
        with self.assertRaises(AccessDenied):
            validate_authorization(response(expiresAt=stamp(NOW+301)), NOW)
        with self.assertRaises(AccessDenied):
            validate_authorization(response(directoryValidUntil=stamp(NOW+600)), NOW)

    def test_old_identity_contract_without_directory_proof_is_rejected(self):
        with self.assertRaises(AccessDenied):
            validate_authorization(response(contractVersion=1), NOW)


if __name__ == '__main__':
    unittest.main()
