import itertools
import json
import threading
import time
import unittest
from datetime import datetime, timezone
from coletor.institutional_access import (AccessDenied, InstitutionalAccess, OnlineResponse,
    PROPOSED_ACCESS_URL, PROPOSED_CAPABILITY, validate_authorization)

NOW = 1791930000


def polls_apart():
    """Monotonic clock where every reading is past the status reuse window."""
    return itertools.count(0, 60).__next__


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
        gate = InstitutionalAccess(provider, clock=lambda: NOW, monotonic=polls_apart(),
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
        gate = InstitutionalAccess(provider, clock=lambda: NOW, monotonic=polls_apart(),
                                   on_locked=lambda: locked.append('revoked'))
        with self.assertRaises(AccessDenied):
            gate.run(lambda: gate.status())
        self.assertTrue(locked)

    def test_simultaneous_status_reads_share_one_online_verification(self):
        started, release = threading.Event(), threading.Event()
        provider = Provider([response()])
        original = provider.verify_online
        def slow_verify():
            started.set()
            release.wait(5)
            return original()
        provider.verify_online = slow_verify
        gate = InstitutionalAccess(provider, clock=lambda: NOW)
        results = []
        def read():
            results.append(gate.status())
        readers = [threading.Thread(target=read) for _ in range(8)]
        readers[0].start()
        self.assertTrue(started.wait(5))
        for reader in readers[1:]:
            reader.start()
        time.sleep(0.05)
        release.set()
        for reader in readers:
            reader.join(5)
        self.assertEqual(len(results), 8)
        self.assertTrue(all(item['authorized'] for item in results))
        self.assertEqual(provider.reads, 1)

    def test_status_reuses_recent_grant_only_inside_window(self):
        now = [0.0]
        provider = Provider([response(), response(), AccessDenied('ACCESS_REQUIRED')])
        gate = InstitutionalAccess(provider, clock=lambda: NOW, monotonic=lambda: now[0])
        self.assertEqual(gate.run(lambda: 'preview'), 'preview')
        now[0] = 4.9
        self.assertTrue(gate.status()['authorized'])
        self.assertEqual(provider.reads, 2)
        now[0] = 10.0
        self.assertEqual(gate.status()['code'], 'ACCESS_REQUIRED')
        self.assertEqual(provider.reads, 3)

    def test_status_never_reuses_an_expired_grant(self):
        clock = [NOW]
        provider = Provider([response(expiresAt=stamp(NOW+2)), AccessDenied('ACCESS_REQUIRED')])
        gate = InstitutionalAccess(provider, clock=lambda: clock[0], monotonic=lambda: 0.0)
        self.assertTrue(gate.status()['authorized'])
        clock[0] = NOW + 2
        self.assertFalse(gate.status()['authorized'])
        self.assertEqual(provider.reads, 2)

    def test_commands_ignore_reusable_grant_and_still_see_revocation(self):
        locked = []
        provider = Provider([response(), response(), response(authorized=False)])
        gate = InstitutionalAccess(provider, clock=lambda: NOW, monotonic=lambda: 0.0,
                                   on_locked=lambda: locked.append('revoked'))
        self.assertTrue(gate.status()['authorized'])
        with self.assertRaises(AccessDenied):
            gate.run(lambda: 'synthetic-capture')
        self.assertEqual(provider.reads, 3)
        self.assertEqual(locked, ['revoked'])
        # The denial drops the reusable grant as well.
        self.assertFalse(gate.status()['authorized'])

    def test_transient_failure_drops_reusable_grant(self):
        provider = Provider([response(), AccessDenied('ACCESS_UNAVAILABLE'), AccessDenied('ACCESS_UNAVAILABLE')])
        gate = InstitutionalAccess(provider, clock=lambda: NOW, monotonic=lambda: 0.0)
        self.assertTrue(gate.status()['authorized'])
        with self.assertRaises(AccessDenied):
            gate.run(lambda: 'synthetic-capture')
        self.assertEqual(gate.status()['code'], 'ACCESS_UNAVAILABLE')

    def test_logout_drops_reusable_grant(self):
        provider = Provider([response(), AccessDenied('ACCESS_REQUIRED')])
        gate = InstitutionalAccess(provider, clock=lambda: NOW, monotonic=lambda: 0.0)
        self.assertTrue(gate.status()['authorized'])
        gate.logout()
        self.assertFalse(gate.status()['authorized'])
        self.assertEqual(provider.reads, 2)

    def test_command_never_joins_verification_started_before_it(self):
        started, release = threading.Event(), threading.Event()
        provider = Provider([response(), response(), response()])
        original = provider.verify_online
        def verify():
            if provider.reads == 0:
                started.set()
                release.wait(5)
            return original()
        provider.verify_online = verify
        gate = InstitutionalAccess(provider, clock=lambda: NOW)
        poll = threading.Thread(target=gate.status)
        poll.start()
        self.assertTrue(started.wait(5))
        done = []
        command = threading.Thread(target=lambda: done.append(gate.run(lambda: 'capture')))
        command.start()
        time.sleep(0.05)
        release.set()
        poll.join(5)
        command.join(5)
        self.assertEqual(done, ['capture'])
        # The poll's request predates the command: it needs two of its own.
        self.assertEqual(provider.reads, 3)

    def test_concurrent_commands_coalesce_but_each_gets_a_later_request(self):
        provider = Provider([response()] * 32)
        lock = threading.Lock()
        original = provider.verify_online
        def slow_verify():
            time.sleep(0.02)
            with lock:
                return original()
        provider.verify_online = slow_verify
        gate = InstitutionalAccess(provider, clock=lambda: NOW)
        barrier = threading.Barrier(8)
        results = []
        def command():
            barrier.wait(5)
            results.append(gate.run(lambda: 'read'))
        workers = [threading.Thread(target=command) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(5)
        self.assertEqual(results, ['read'] * 8)
        self.assertLess(provider.reads, 16)

    def test_denied_shared_verification_cleans_up_once_and_denies_everyone(self):
        started, release = threading.Event(), threading.Event()
        locked = []
        provider = Provider([response(), response(authorized=False)])
        original = provider.verify_online
        def verify():
            if provider.reads == 1:
                started.set()
                release.wait(5)
            return original()
        provider.verify_online = verify
        gate = InstitutionalAccess(provider, clock=lambda: NOW, monotonic=polls_apart(),
                                   on_locked=lambda: locked.append('revoked'))
        self.assertTrue(gate.status()['authorized'])
        results = []
        readers = [threading.Thread(target=lambda: results.append(gate.status())) for _ in range(5)]
        readers[0].start()
        self.assertTrue(started.wait(5))
        for reader in readers[1:]:
            reader.start()
        time.sleep(0.05)
        release.set()
        for reader in readers:
            reader.join(5)
        self.assertEqual(len(results), 5)
        self.assertFalse(any(item['authorized'] for item in results))
        self.assertEqual(provider.reads, 2)
        self.assertEqual(locked, ['revoked'])

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

    def test_denied_background_polls_never_close_an_unauthorized_source(self):
        from unittest.mock import Mock
        cleanup = Mock(side_effect=RuntimeError('synthetic-close-not-allowed'))
        provider = Provider([AccessDenied('ACCESS_REQUIRED'),
                             AccessDenied('PAIRING_PENDING'),
                             AccessDenied('ACCESS_REQUIRED')])
        gate = InstitutionalAccess(provider, clock=lambda: NOW, on_locked=cleanup)
        self.assertEqual(gate.status()['code'], 'ACCESS_REQUIRED')
        self.assertEqual(gate.status()['code'], 'PAIRING_PENDING')
        self.assertEqual(gate.status()['code'], 'ACCESS_REQUIRED')
        cleanup.assert_not_called()
        self.assertFalse(gate._cleanup_pending)
        gate.open_login()
        self.assertTrue(provider.opened)
        cleanup.assert_not_called()

    def test_first_failed_authenticated_poll_cancels_once_not_on_every_poll(self):
        from unittest.mock import Mock
        cleanup = Mock()
        provider = Provider([response(), AccessDenied('ACCESS_REQUIRED'),
                             AccessDenied('ACCESS_REQUIRED')])
        gate = InstitutionalAccess(provider, clock=lambda: NOW, monotonic=polls_apart(), on_locked=cleanup)
        self.assertTrue(gate.status()['authorized'])
        self.assertFalse(gate.status()['authorized'])
        self.assertFalse(gate.status()['authorized'])
        cleanup.assert_called_once()
        self.assertFalse(gate._cleanup_pending)

    def test_cleanup_failure_keeps_gate_locked(self):
        def failed_cleanup():
            raise RuntimeError('private browser cleanup failed')
        provider = Provider([response(), response(authorized=False)])
        gate = InstitutionalAccess(provider, clock=lambda: NOW, monotonic=polls_apart(), on_locked=failed_cleanup)
        self.assertTrue(gate.status()['authorized'])
        self.assertFalse(gate.status()['authorized'])
        self.assertEqual(gate.status()['code'], 'ACCESS_CLEANUP_PENDING')
        self.assertEqual(provider.reads, 2)
        with self.assertRaises(AccessDenied):
            gate.open_login()

    def test_transient_worker_cleanup_is_retried_before_opening_browser(self):
        from unittest.mock import Mock
        cleanup = Mock(side_effect=[RuntimeError('synthetic-worker-close'), None])
        provider = Provider([response()])
        gate = InstitutionalAccess(provider, clock=lambda: NOW, on_locked=cleanup)
        self.assertTrue(gate.status()['authorized'])
        gate.open_login()
        self.assertTrue(provider.opened)
        self.assertFalse(gate._cleanup_pending)
        self.assertEqual(cleanup.call_count, 2)

    def test_repeated_worker_cleanup_failure_still_denies_login(self):
        from unittest.mock import Mock
        cleanup = Mock(side_effect=RuntimeError('synthetic-unclosed-worker'))
        provider = Provider([response()])
        gate = InstitutionalAccess(provider, clock=lambda: NOW, on_locked=cleanup)
        self.assertTrue(gate.status()['authorized'])
        with self.assertRaises(AccessDenied) as caught:
            gate.open_login()
        self.assertEqual(caught.exception.code, 'ACCESS_CLEANUP_PENDING')
        self.assertFalse(provider.opened)
        self.assertTrue(gate._cleanup_pending)

    def test_failed_device_logout_cannot_be_cleared_by_worker_cleanup(self):
        from unittest.mock import Mock
        provider = Provider([])
        provider.close = Mock(side_effect=[RuntimeError('synthetic-device-failure'), None])
        cleanup = Mock()
        gate = InstitutionalAccess(provider, clock=lambda: NOW, on_locked=cleanup)
        with self.assertRaises(AccessDenied):
            gate.logout()
        self.assertTrue(gate._cleanup_pending)
        with self.assertRaises(AccessDenied) as caught:
            gate.open_login()
        self.assertEqual(caught.exception.code, 'ACCESS_CLEANUP_PENDING')
        self.assertFalse(provider.opened)
        provider.close.assert_called_once()
        gate.logout()
        gate.open_login()
        self.assertTrue(provider.opened)
        self.assertFalse(gate._cleanup_pending)

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
