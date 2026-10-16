"""Operational regressions with synthetic classes and students; no real login."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from coletor.device_provider import FrequencyError
import coletor.frequency_runtime as frequency_runtime
from coletor.frequency_runtime import FrequencyRuntime, collection_payload, validate_schedule
from coletor.institutional_access import AccessDenied
from coletor.protected_storage import Dpapi, ProtectedStorage, StorageError
from coletor.instance_lock import CollectorInstance
from coletor.manual_session import SessionError

NOW = 1791993600
DEVICE = '11111111-1111-4111-8111-111111111111'


def stamp(value): return datetime.fromtimestamp(value, timezone.utc).isoformat()


def schedule():
    return {'timezone': 'America/Bahia', 'rules': [{'weekday': day, 'shift': shift, 'enabled': False,
            'times': [], 'recheck': None} for day in range(7) for shift in ['matutino', 'vespertino']]}


class SyntheticCrypto:
    def protect(self, data, entropy): return entropy + b'\0' + bytes(b ^ 91 for b in data)
    def unprotect(self, data, entropy):
        if not data.startswith(entropy + b'\0'): raise StorageError()
        return bytes(b ^ 91 for b in data[len(entropy) + 1:])


class Access:
    def __init__(self): self.denied = False; self.calls = 0
    def run(self, work):
        self.calls += 1
        if self.denied: raise AccessDenied()
        result = work()
        if self.denied: raise AccessDenied()
        return result


class Provider:
    def __init__(self):
        self.now = NOW
        self.requests = []
        self.fence = 0
        self.results = {}
        self.paused = False
        self.shared_schedule = schedule()
        self.fail_after_commit = False
        self.fail_lease = False
        self.revision = 0
    def storage_binding(self): return DEVICE, 1
    def frequency_request(self, payload):
        self.requests.append(copy.deepcopy(payload))
        operation = payload['operation']
        if operation == 'status':
            return {'contractVersion': 2, 'state': 'ready', 'academicYear': 2026, 'serverTime': stamp(self.now),
                    'classes': [{'classId': 10, 'sourceClassLabel': 'TURMA SINTÉTICA A', 'shift': 'matutino', 'revision': self.revision}],
                    'settings': {'revision': 0, 'paused': self.paused, 'schedule': self.shared_schedule}}
        if operation == 'receipt': return {'contractVersion': 2, 'state': 'ready', 'operation': 'receipt', 'requestId': payload['requestId'], 'result': self.results.get(payload['requestId'])}
        result = {'contractVersion': 2, 'state': 'committed', 'operation': operation, 'requestId': payload['requestId']}
        if operation == 'lease':
            if self.fail_lease: raise FrequencyError('lease-busy')
            self.fence += 1
            result.update(fencingToken=self.fence, expiresAt=stamp(self.now + 120), settingsRevision=0)
        elif operation == 'heartbeat': result.update(fencingToken=payload['fencingToken'], expiresAt=stamp(self.now + 100))
        elif operation == 'collect':
            if payload['fencingToken'] != self.fence: raise FrequencyError('lease-fenced')
            if payload['expectedRevision'] != self.revision: raise FrequencyError('revision-conflict')
            result.update(classId=payload['classId'], revision=self.revision + 1, receivedAt=stamp(self.now), resolvedRecords=1, unresolvedRecords=0, conflicts=0)
            self.revision += 1
        elif operation == 'save-settings':
            if payload['expectedRevision'] != 0: raise FrequencyError('revision-conflict')
            self.shared_schedule = payload['schedule']
            result['settingsRevision'] = 1
        elif operation == 'set-paused': self.paused = payload['paused']; result['settingsRevision'] = 1
        elif operation == 'release': result.update(fencingToken=payload['fencingToken'], expiresAt=None)
        self.results[payload['requestId']] = copy.deepcopy(result)
        if operation == 'collect' and self.fail_after_commit:
            self.fail_after_commit = False
            raise FrequencyError('unavailable')
        return result


def preview():
    return {'mode': 'manual', 'snapshot': {'source_format': 'smecel-annual-v1', 'snapshot_id': 'a' * 64,
            'year': 2026, 'class_id': '13331', 'students': [{'source_student_ref': 'row:1', 'display_name': 'ALUNO SINTÉTICO', 'original_class': 'TURMA SINTÉTICA A'}],
            'records': [{'source_student_ref': 'row:1', 'date': '2026-02-23', 'lesson': 6, 'state': 'absent'},
                        {'source_student_ref': 'row:1', 'date': '2026-02-24', 'lesson': 1, 'state': 'excused_absent'},
                        {'source_student_ref': 'row:1', 'date': '2026-02-25', 'lesson': 1, 'state': 'planned_unknown'},
                        {'source_student_ref': 'row:1', 'date': '2026-12-25', 'lesson': 6, 'state': 'absent'}]},
            'capture': {'destination': 'local_memory', 'captured_at': stamp(NOW), 'html_sha256': 'b' * 64}}


class Source:
    def __init__(self): self.closed = 0; self.reads = 0; self.on_capture = lambda: None
    def operational_catalog(self, storage):
        return {'selected_class_ids': ['13331'], 'unavailable_class_ids': [], 'catalog': {'classes': [
                {'class_id': '13331', 'name': 'TURMA SINTÉTICA A', 'shift': 'matutino'}]}}
    def operational_capture(self, class_id): self.reads += 1; self.on_capture(); return preview()
    def preserve_and_close(self, storage): self.close()
    def remember_if_ready(self, storage): pass
    def close(self): self.closed += 1


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.provider, self.access, self.source = Provider(), Access(), Source()
        self.storage = ProtectedStorage(self.directory.name, crypto=SyntheticCrypto(), consent=lambda: True, clock=lambda: self.provider.now)
        self.storage.bind(DEVICE, 1)
        self.runtime = FrequencyRuntime(self.access, self.provider, self.source, storage=self.storage, clock=lambda: self.provider.now)
        # No actual timer thread or native dialog in domain tests.
        self.runtime._active = True
        self.addCleanup(self.runtime.shutdown)

    def test_real_flow_selected_worker_sparse_sixth_slot_receipt_and_no_uid(self):
        result = self.runtime.collect()
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['lastReceipt']['resolvedRecords'], 1)
        payload = next(r for r in self.provider.requests if r['operation'] == 'collect')
        self.assertEqual([m['mark'] for m in payload['marks']], ['X', 'J'])
        self.assertEqual(payload['marks'][0]['slot'], 6)
        self.assertFalse(payload['rosterComplete'])
        self.assertTrue(all(not c['complete'] for c in payload['coverage']))
        self.assertNotIn('studentUid', json.dumps(payload))
        self.assertEqual(self.storage.queue(), [])
        self.assertGreater(self.access.calls, 6)

    def test_uncertain_send_consults_receipt_before_retry_and_never_duplicates(self):
        self.provider.fail_after_commit = True
        result = self.runtime.collect()
        self.assertEqual(result['state'], 'ready')
        operations = [r['operation'] for r in self.provider.requests]
        index = operations.index('collect')
        self.assertEqual(operations[index + 1], 'receipt')
        self.assertEqual(operations.count('collect'), 1)

    def test_lease_busy_reserve_does_not_open_source(self):
        self.provider.fail_lease = True
        self.assertEqual(self.runtime.collect()['state'], 'reserve')
        self.assertEqual(self.source.reads, 0)

    def test_revoked_gate_and_late_capture_cannot_enqueue_or_send(self):
        self.source.on_capture = lambda: self.runtime.cancel(purge=True)
        self.runtime.collect()
        self.assertFalse(any(p['operation'] == 'collect' for p in self.provider.requests))
        self.assertEqual(self.storage.queue(), [])
        self.assertIsNone(self.runtime._status)
        self.assertEqual(self.runtime.public_status()['progress']['total'], 0)

    def test_capture_identity_changed_gate_blocks_after_command(self):
        self.source.on_capture = lambda: setattr(self.access, 'denied', True)
        self.runtime.collect()
        self.assertFalse(any(p['operation'] == 'collect' for p in self.provider.requests))

    def test_school_pause_and_local_pause_block_source(self):
        self.provider.paused = True
        self.assertEqual(self.runtime.collect()['state'], 'paused')
        self.assertEqual(self.source.reads, 0)

    def test_remote_school_resume_does_not_leave_all_reserves_locally_paused(self):
        self.provider.paused = True
        self.runtime.tick()
        self.assertFalse(self.runtime.public_status()['localPaused'])
        self.provider.paused = False
        self.runtime.tick()
        self.assertFalse(self.runtime._school_paused)
        self.assertIsNone(self.runtime._lease)  # Idle polling never takes school leadership.

    def test_skewed_windows_clock_blocks_capture_with_actionable_code(self):
        self.runtime._clock = lambda: self.provider.now + 11
        with self.assertRaises(FrequencyError) as caught:
            self.runtime._fresh()
        self.assertEqual(caught.exception.code, 'CLOCK_OUT_OF_SYNC')
        self.runtime._clock = lambda: self.provider.now - 11
        with self.assertRaises(FrequencyError) as caught:
            self.runtime._fresh()
        self.assertEqual(caught.exception.code, 'CLOCK_OUT_OF_SYNC')
        self.runtime._clock = lambda: self.provider.now
        self.assertEqual(self.runtime._fresh()['state'], 'ready')

    def test_eligible_leader_heartbeats_but_known_source_failure_releases_leadership(self):
        current = datetime.fromtimestamp(NOW, timezone.utc).astimezone(
            __import__('zoneinfo').ZoneInfo('America/Bahia'))
        rules = schedule()
        rule = next(r for r in rules['rules'] if r['weekday'] == (current.weekday()+1)%7)
        rule['enabled'] = True
        rule['times'] = ['00:00' if current.strftime('%H:%M') != '00:00' else '00:01']
        self.provider.shared_schedule = rules
        self.runtime.tick()
        operations = [p['operation'] for p in self.provider.requests]
        self.assertIn('heartbeat', operations)
        self.assertEqual(operations.count('lease'), 1)
        self.runtime._source_blocked = True
        self.provider.now += 121
        self.runtime.tick()
        self.assertEqual(sum(p['operation']=='lease' for p in self.provider.requests), 1)

    def test_newly_selected_source_clears_no_selection_block(self):
        self.runtime._code, self.runtime._state = 'NO_SELECTED_CLASSES', 'error'
        self.runtime.source_ready()
        self.assertIsNone(self.runtime._code)
        self.assertEqual(self.runtime._state, 'reserve')

    def test_idle_scheduler_and_blocked_source_never_take_school_leadership(self):
        self.runtime.tick()
        self.assertNotIn('lease', [p['operation'] for p in self.provider.requests])
        self.runtime._source_blocked = True
        self.runtime.collect()
        self.assertNotIn('lease', [p['operation'] for p in self.provider.requests])
        self.assertEqual(self.runtime.public_status()['code'], 'SOURCE_LOGIN_REQUIRED')

    def test_two_computers_fail_over_when_selection_is_missing_or_cleared(self):
        # One school lease, two distinct device identities, deterministic clock.
        # Neither the missing persisted choice nor an empty live Smecel catalog
        # is allowed to strand the healthy reserve during the scheduled minute.
        current = datetime.fromtimestamp(NOW, timezone.utc).astimezone(
            __import__('zoneinfo').ZoneInfo('America/Bahia'))
        rules = schedule()
        today = next(r for r in rules['rules']
                     if r['weekday'] == (current.weekday() + 1) % 7 and r['shift'] == 'matutino')
        today['enabled'] = True
        today['times'] = ['00:00' if current.strftime('%H:%M') != '00:00' else '00:01']
        school = {'lease': None, 'fence': 0}

        class SchoolProvider(Provider):
            def __init__(self, device_id):
                super().__init__()
                self.device_id = device_id
                self.shared_schedule = rules

            def storage_binding(self):
                return self.device_id, 1

            def frequency_request(self, payload):
                op = payload['operation']
                if op == 'status':
                    result = super().frequency_request(payload)
                    result['lease'] = copy.deepcopy(school['lease'])
                    return result
                if op in {'lease', 'heartbeat', 'release'}:
                    self.requests.append(copy.deepcopy(payload))
                    existing = school['lease']
                    if op == 'lease':
                        if existing and existing['deviceId'] != self.device_id:
                            raise FrequencyError('lease-busy')
                        school['fence'] += 1
                        school['lease'] = {'deviceId': self.device_id,
                                           'fencingToken': school['fence'],
                                           'expiresAt': stamp(self.now + 120)}
                        existing = school['lease']
                    elif (existing is None or existing['deviceId'] != self.device_id
                          or existing['fencingToken'] != payload['fencingToken']):
                        raise FrequencyError('lease-fenced')
                    if op == 'release':
                        school['lease'] = None
                    return {'contractVersion': 2, 'state': 'committed', 'operation': op,
                            'requestId': payload['requestId'], 'fencingToken': existing['fencingToken'],
                            'expiresAt': None if op == 'release' else existing['expiresAt']}
                if op == 'collect':
                    self.fence = school['fence']
                return super().frequency_request(payload)

        def peer(device_id):
            provider = SchoolProvider(device_id)
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            storage = ProtectedStorage(directory.name, crypto=SyntheticCrypto(),
                                       consent=lambda: True, clock=lambda: provider.now)
            storage.bind(device_id, 1)
            source = Source()
            selected = [True]
            source.has_saved_class_selection = lambda: selected[0]
            runtime = FrequencyRuntime(Access(), provider, source,
                                       storage=storage, clock=lambda: provider.now)
            runtime._active = True
            self.addCleanup(runtime.shutdown)
            return runtime, provider, source, selected

        primary, provider_a, source_a, selected_a = peer(DEVICE)
        backup, provider_b, source_b, selected_b = peer('22222222-2222-4222-8222-222222222222')
        selected_a[0] = False
        primary.tick()
        self.assertEqual(primary.public_status()['code'], 'NO_SELECTED_CLASSES')
        self.assertNotIn('lease', [r['operation'] for r in provider_a.requests])
        backup.tick()
        self.assertEqual(school['lease']['deviceId'], provider_b.device_id)

        # A selection added while the reserve is collecting must not steal it.
        selected_a[0] = True
        primary.source_ready()
        with self.assertRaises(FrequencyError) as busy:
            primary.tick()
        self.assertEqual(busy.exception.code, 'lease-busy')

        # An existing leader that loses its selection yields immediately.
        selected_b[0] = False
        backup.tick()
        self.assertIsNone(school['lease'])
        self.assertIn('release', [r['operation'] for r in provider_b.requests])
        primary.tick()
        self.assertEqual(school['lease']['deviceId'], provider_a.device_id)

        # A saved selection is only a hint: if live discovery finds no
        # selected classes, the error also releases the school's lease.
        source_a.operational_catalog = lambda storage: {
            'selected_class_ids': [], 'unavailable_class_ids': [],
            'catalog': {'classes': []}}
        primary.collect()
        self.assertEqual(primary.public_status()['code'], 'NO_SELECTED_CLASSES')
        self.assertIsNone(school['lease'])
        selected_b[0] = True
        backup.source_ready()
        backup.tick()
        self.assertEqual(school['lease']['deviceId'], provider_b.device_id)

    def test_heartbeat_temporary_failure_does_not_cancel_a_valid_capture(self):
        class QuickEvent(threading.Event):
            def wait(self, timeout=None):
                return super().wait(None if timeout is None else min(timeout, 0.02))

        original = self.provider.frequency_request
        failures = []

        def transient(payload):
            if payload['operation'] == 'heartbeat':
                failures.append(True)
                raise FrequencyError('unavailable')
            return original(payload)

        self.provider.frequency_request = transient
        self.source.on_capture = lambda: time.sleep(0.12)
        with patch.object(frequency_runtime.threading, 'Event', QuickEvent):
            result = self.runtime.collect()
        self.assertTrue(failures)
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['lastReceipt']['resolvedRecords'], 1)
        self.assertEqual(self.storage.queue(), [])

    def test_discard_after_annual_reset_requires_confirmation_without_replay(self):
        self.storage.enqueue({'requestId': DEVICE, 'operation': 'collect', 'academicYear': 2026})
        self.runtime._receipt = Mock(side_effect=FrequencyError('revision-conflict'))
        self.runtime._confirm_discard = Mock(return_value=True)
        self.runtime.discard_queue()
        self.assertEqual(self.storage.queue(), [])
        self.runtime._confirm_discard.assert_called_once()
        self.runtime._receipt.assert_called_once()

    def test_activation_declined_persistence_keeps_memory_and_no_source_loop(self):
        self.runtime._active = False
        self.runtime._thread = Mock()  # No actual background timer in this fixture.
        self.storage._consent = Mock(return_value=False)
        self.source.remember_if_ready = Mock()
        result = self.runtime.activate()
        self.assertTrue(result['active'])
        self.assertFalse(result['rememberSession'])
        self.assertFalse(self.storage.directory.exists())
        self.source.remember_if_ready.assert_called_once_with(self.storage)

    def test_discard_reconciles_receipt_first_and_requires_native_confirmation(self):
        payload = collection_payload(preview(), {'class_id': '13331', 'name': 'TURMA SINTÉTICA A'},
                                     {'classId': 10, 'sourceClassLabel': 'TURMA SINTÉTICA A', 'revision': 0}, 99, DEVICE)
        self.storage.enqueue(payload)
        self.runtime._confirm_discard = Mock(return_value=False)
        with self.assertRaises(FrequencyError): self.runtime.discard_queue()
        self.assertEqual(self.provider.requests[-1]['operation'], 'receipt')
        self.assertEqual(len(self.storage.queue()), 1)
        self.runtime._confirm_discard.return_value = True
        self.runtime.discard_queue()
        self.assertEqual(self.storage.queue(), [])
        self.provider.paused = False
        self.runtime.local_pause(True)
        self.runtime.collect()
        self.assertEqual(self.source.reads, 0)

    def test_expired_capture_gets_new_lease_before_first_attempt(self):
        self.source.on_capture = lambda: setattr(self.provider, 'now', NOW + 130)
        self.assertEqual(self.runtime.collect()['state'], 'ready')
        payload = next(p for p in self.provider.requests if p['operation'] == 'collect')
        self.assertEqual(payload['fencingToken'], 3)

    def test_capture_slower_than_lease_is_not_cancelled_by_heartbeat(self):
        class QuickEvent(threading.Event):
            def wait(self, timeout=None): return super().wait(None if timeout is None else min(timeout, 0.02))

        def slow_capture():
            self.provider.now = NOW + 130  # The 120-second grant lapses mid-capture.
            time.sleep(0.3)                # Heartbeat thread runs several times.
        self.source.on_capture = slow_capture
        with patch.object(frequency_runtime.threading, 'Event', QuickEvent):
            result = self.runtime.collect()
        self.assertEqual(result['state'], 'ready')
        payload = next(p for p in self.provider.requests if p['operation'] == 'collect')
        self.assertEqual(payload['fencingToken'], self.provider.fence)

    def test_slow_status_and_lease_do_not_fence_a_fresh_grant(self):
        original = self.provider.frequency_request

        def delayed(payload):
            if payload['operation'] == 'status':
                response = original(payload)
                self.provider.now += 8  # Delay after serverTime was sampled.
                return response
            if payload['operation'] == 'lease':
                self.provider.now += 7  # Grant is issued after the request begins.
            return original(payload)

        self.provider.frequency_request = delayed
        status = self.runtime._fresh()
        lease_request_started = self.provider.now
        self.runtime._acquire(status)
        self.assertEqual(self.runtime._lease['fencingToken'], 1)
        self.assertEqual(self.runtime._lease['deadline'], lease_request_started + 118)
        self.assertGreater(self.runtime._lease['deadline'], self.provider.now)

    def test_stale_status_must_not_reuse_an_expired_own_lease(self):
        status = self.runtime._fresh()
        status['lease'] = {'deviceId': DEVICE, 'fencingToken': 50,
                           'expiresAt': stamp(self.provider.now + 10)}
        self.provider.now += 20  # Transport delay or delayed consumer.
        self.runtime._acquire(status)
        self.assertEqual(self.runtime._lease['fencingToken'], 1)

    def test_heartbeat_never_extends_lease_when_response_is_delayed(self):
        self.runtime._lease = {'fencingToken': 1, 'deadline': NOW + 40}
        old_deadline = self.runtime._lease['deadline']
        original = self.provider.frequency_request

        def delayed(payload):
            response = original(payload)
            if payload['operation'] == 'heartbeat':
                self.provider.now += 5
            return response

        self.provider.frequency_request = delayed
        self.runtime._heartbeat(self.runtime._epoch)
        self.assertLessEqual(self.runtime._lease['deadline'], old_deadline)

    def test_old_pending_fence_queries_receipt_then_requires_recapture(self):
        payload = collection_payload(preview(), {'class_id': '13331', 'name': 'TURMA SINTÉTICA A'},
                                     {'classId': 10, 'sourceClassLabel': 'TURMA SINTÉTICA A', 'revision': 0}, 500, DEVICE)
        self.storage.enqueue(payload)
        result = self.runtime.collect()
        self.assertEqual(result['code'], 'lease-fenced')
        self.assertEqual(self.source.reads, 0)
        self.assertEqual(self.storage.queue()[0]['payload'], payload)

    def test_settings_conflict_preserves_shared_schedule(self):
        before = copy.deepcopy(self.provider.shared_schedule)
        with self.assertRaises(FrequencyError): self.runtime.save_settings(99, schedule())
        self.assertEqual(self.provider.shared_schedule, before)

    def test_expired_source_login_does_not_loop_or_launch(self):
        self.source.operational_catalog = Mock(side_effect=SessionError('expired'))
        result = self.runtime.collect()
        self.assertEqual(result['state'], 'login-required')
        self.source.operational_catalog.assert_called_once()
        self.assertEqual(self.source.reads, 0)
        self.runtime.collect()
        self.source.operational_catalog.assert_called_once()

    def test_pause_arriving_during_capture_blocks_before_enqueue_or_post(self):
        self.source.on_capture = lambda: setattr(self.provider, 'paused', True)
        result = self.runtime.collect()
        self.assertEqual(result['state'], 'paused')
        self.assertFalse(any(p['operation'] == 'collect' for p in self.provider.requests))
        self.assertEqual(self.storage.queue(), [])

    def test_queue_dpapi_failure_never_reports_collection_success(self):
        self.storage.enable()
        self.storage._crypto.protect = Mock(side_effect=StorageError())
        result = self.runtime.collect()
        self.assertEqual(result['state'], 'error')
        self.assertIsNone(result['lastReceipt'])
        self.assertFalse(any(p['operation'] == 'collect' for p in self.provider.requests))

    def test_unknown_symbols_keep_known_sparse_marks_without_completeness(self):
        from test_manual_session import raw_fixture
        from coletor.manual_session import captured_preview, source_url
        html = raw_fixture().replace('ls-color-danger">X', 'ls-color-danger">?', 1)
        payload = {'url': source_url('13331', 2026), 'password_form': False, 'html': html}
        with self.assertRaises(SessionError): captured_preview(payload, '13331', 2026)
        result = captured_preview(payload, '13331', 2026, allow_partial=True)
        self.assertTrue(any(i['code'] == 'SOURCE_SYMBOL_UNKNOWN' for i in result['snapshot']['issues']))
        self.assertTrue(any(r['state'] == 'absent' for r in result['snapshot']['records']))
        self.assertFalse(result['capture']['roster_complete_verified'])

    def test_clock_rollback_does_not_freeze_scheduler(self):
        self.runtime._last_tick = NOW + 3600
        self.provider.now = NOW
        self.runtime.tick = Mock()

        class OneCycle:
            def __init__(self): self.calls = 0
            def wait(self, _seconds):
                self.calls += 1
                return self.calls > 1
            def set(self): self.calls = 100

        self.runtime._stop = OneCycle()
        self.runtime._loop()
        self.runtime.tick.assert_called_once()
        self.assertEqual(self.runtime._last_tick, NOW)

    def test_schedule_tick_consumes_only_current_minute_no_replay(self):
        now = datetime.fromtimestamp(NOW, timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('America/Bahia'))
        value = schedule()
        rule = next(r for r in value['rules'] if r['weekday'] == (now.weekday() + 1) % 7 and r['shift'] == 'matutino')
        rule.update(enabled=True, times=[now.strftime('%H:%M')])
        self.provider.shared_schedule = value
        self.runtime.collect = Mock()
        self.runtime.tick()
        import time
        time.sleep(.02)
        self.runtime.tick()
        self.assertEqual(self.runtime.collect.call_count, 1)
        self.assertFalse(self.runtime._operation.locked())
        self.provider.now += 120
        self.runtime.tick()
        self.assertEqual(self.runtime.collect.call_count, 1)

    def test_preview_or_different_header_cannot_be_promoted(self):
        value = preview(); value['mode'] = 'demo'
        source = {'class_id': '13331', 'name': 'TURMA SINTÉTICA A'}
        central = {'classId': 10, 'sourceClassLabel': 'TURMA SINTÉTICA A', 'revision': 0}
        with self.assertRaises(FrequencyError): collection_payload(value, source, central, 1, DEVICE)

    def test_source_refs_are_stable_across_reobservation_but_not_identity_authority(self):
        first = preview()
        second = copy.deepcopy(first)
        second['snapshot']['snapshot_id'] = 'c' * 64
        second['capture']['captured_at'] = stamp(NOW + 60)
        source = {'class_id': '13331', 'name': 'TURMA SINTÉTICA A'}
        central = {'classId': 10, 'sourceClassLabel': 'TURMA SINTÉTICA A', 'revision': 0}
        one = collection_payload(first, source, central, 1, DEVICE)
        two = collection_payload(second, source, central, 2, DEVICE)
        self.assertEqual(one['records'], two['records'])
        self.assertEqual(one['marks'], two['marks'])
        self.assertNotEqual(one['sourceVersion'], two['sourceVersion'])
        self.assertNotIn('ALUNO', one['records'][0]['recordKey'])
        changed = copy.deepcopy(first)
        changed['snapshot']['students'][0]['display_name'] = 'OUTRO ALUNO SINTÉTICO'
        self.assertNotEqual(one['records'][0]['recordKey'], collection_payload(changed, source, central, 1, DEVICE)['records'][0]['recordKey'])
        value = preview(); value['snapshot']['students'][0]['original_class'] = 'OUTRA TURMA'
        with self.assertRaises(FrequencyError): collection_payload(value, source, central, 1, DEVICE)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.now = NOW
        self.storage = ProtectedStorage(self.directory.name, crypto=SyntheticCrypto(), consent=lambda: True, clock=lambda: self.now)
        self.storage.bind(DEVICE, 1)

    def test_consent_precedes_persistence_and_data_is_ciphertext(self):
        payload = {'requestId': DEVICE, 'marks': ['ALUNO SINTÉTICO']}
        self.storage.enqueue(payload)
        self.assertFalse(self.storage.directory.exists())
        self.storage.enable(); self.storage.enqueue({'requestId': 'second', 'marks': ['PRIVATE SYNTHETIC']})
        raw = (self.storage.directory / 'queue.dpapi').read_bytes()
        self.assertNotIn(b'PRIVATE SYNTHETIC', raw)
        restored = ProtectedStorage(self.directory.name, crypto=SyntheticCrypto()); restored.bind(DEVICE, 1)
        self.assertEqual(len(restored.queue()), 2)
        before = (restored.directory / 'queue.dpapi').read_bytes()
        with self.assertRaises(StorageError) as prevented:
            restored.bind(DEVICE, 2)
        self.assertEqual(prevented.exception.code, 'PENDING_BATCHES')
        self.assertEqual((restored.directory / 'queue.dpapi').read_bytes(), before)
        self.assertEqual(len(restored.queue()), 2)
        restored.acknowledge(DEVICE)
        restored.acknowledge('second')
        restored.bind(DEVICE, 2)
        self.assertEqual(restored.queue(), [])

    def test_binding_switch_preserves_unreceipted_memory_queue(self):
        self.storage.enqueue({'requestId': 'pending-in-memory', 'marks': ['X']})
        with self.assertRaises(StorageError) as prevented:
            self.storage.bind('other-device', 2)
        self.assertEqual(prevented.exception.code, 'PENDING_BATCHES')
        self.assertEqual(self.storage._binding, f'{DEVICE}:1')
        self.assertEqual(self.storage.queue()[0]['payload']['requestId'], 'pending-in-memory')
        self.storage.acknowledge('pending-in-memory')
        self.storage.bind('other-device', 2)
        self.assertEqual(self.storage.queue(), [])

    def test_corrupt_old_queue_blocks_generation_switch_without_deleting_blob(self):
        self.storage.enable()
        self.storage.enqueue({'requestId': 'pending-on-disk'})
        path = self.storage.directory / 'queue.dpapi'
        path.write_bytes(b'corrupt')
        with self.assertRaises(StorageError):
            self.storage.bind(DEVICE, 2)
        self.assertEqual(path.read_bytes(), b'corrupt')
        self.assertEqual(self.storage._binding, f'{DEVICE}:1')

    def test_wrong_device_and_corrupt_dpapi_fail_closed(self):
        self.storage.enable(); self.storage.enqueue({'requestId': DEVICE})
        wrong = ProtectedStorage(self.directory.name, crypto=SyntheticCrypto()); wrong.bind('another-device', 1)
        with self.assertRaises(StorageError): wrong.queue()
        (self.storage.directory / 'queue.dpapi').write_bytes(b'corrupt')
        with self.assertRaises(StorageError): self.storage.queue()

    def test_expiry_and_clear_touch_only_owned_files(self):
        self.storage.enable(); self.storage.enqueue({'requestId': DEVICE})
        sentinel = Path(self.directory.name) / 'other-app'; sentinel.write_text('preserve')
        self.now += 7 * 86400 + 1
        self.assertEqual(self.storage.queue(), [])
        self.storage.clear()
        self.assertEqual(sentinel.read_text(), 'preserve')

    def test_clock_rollback_preserves_pending_receipts_instead_of_deleting_queue(self):
        self.storage.enqueue({'requestId': DEVICE, 'marks': ['X']})
        self.now -= 3600  # Windows clock corrected backward after collection.
        with self.assertRaises(StorageError):
            self.storage.queue()
        self.now += 3600
        self.assertEqual([v['payload']['requestId'] for v in self.storage.queue()], [DEVICE])

    def test_source_restore_rejects_other_origins_and_no_partial_session(self):
        with self.assertRaises(StorageError): self.storage.save_session({'cookies': [], 'origins': [{'origin': 'https://evil.invalid'}]})

    def test_interprocess_lock_excludes_second_instance_and_releases(self):
        first = CollectorInstance(self.directory.name).acquire()
        try:
            with self.assertRaises(RuntimeError): CollectorInstance(self.directory.name).acquire()
        finally: first.close()
        CollectorInstance(self.directory.name).acquire().close()

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows DPAPI')
    def test_native_dpapi_user_entropy_roundtrip_no_named_key(self):
        crypto = Dpapi()
        raw = crypto.protect(b'only-synthetic-session', b'collector-native-test')
        self.assertNotIn(b'only-synthetic-session', raw)
        self.assertEqual(crypto.unprotect(raw, b'collector-native-test'), b'only-synthetic-session')
        with self.assertRaises(StorageError): crypto.unprotect(raw, b'other-purpose')

    def test_weekend_timezone_limits_validated_without_localstorage(self):
        self.assertEqual(validate_schedule(schedule())['timezone'], 'America/Bahia')
        invalid = schedule(); invalid['timezone'] = 'invalid/zone'
        with self.assertRaises(FrequencyError): validate_schedule(invalid)
        invalid = schedule(); invalid['rules'][0]['times'] = ['08:00'] * 17
        with self.assertRaises(FrequencyError): validate_schedule(invalid)
