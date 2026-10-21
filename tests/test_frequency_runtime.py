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
from coletor.frequency_runtime import FrequencyRuntime, collection_payload, lessons_per_day, validate_schedule
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
    def __init__(self): self.denied = False; self.calls = 0; self.depth = 0
    def run(self, work):
        self.calls += 1
        if self.denied: raise AccessDenied()
        self.depth += 1
        try: result = work()
        finally: self.depth -= 1
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
            result.update(fencingToken=self.fence, expiresAt=stamp(self.now + payload['durationSeconds']), settingsRevision=0)
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
        outside, request = [], self.provider.frequency_request
        def bracketed(payload):
            if self.access.depth == 0: outside.append(payload['operation'])
            return request(payload)
        self.provider.frequency_request = bracketed
        captured = []
        self.source.on_capture = lambda: captured.append(self.access.depth)
        result = self.runtime.collect()
        self.assertEqual(result['state'], 'ready', repr(result))
        self.assertEqual(result['lastReceipt']['resolvedRecords'], 1)
        payload = next(r for r in self.provider.requests if r['operation'] == 'collect')
        self.assertEqual([m['mark'] for m in payload['marks']], ['X', 'J'])
        self.assertEqual(payload['marks'][0]['slot'], 6)
        self.assertFalse(payload['rosterComplete'])
        # Lesson days (owner decision 20/10/2026): every lesson position up to the capture, the point
        # of 25/02 included, each day complete; the future 25/12 is never sent.
        self.assertEqual([(c['date'], c['slots'], c['complete']) for c in payload['coverage']],
                         [('2026-02-23', [6], True), ('2026-02-24', [1], True), ('2026-02-25', [1], True)])
        self.assertNotIn('studentUid', json.dumps(payload))
        self.assertEqual(self.storage.queue(), [])
        # Every server request and the source read run inside a verified
        # bracket. Per class: status+lease+read+status share one; send has its own.
        self.assertEqual(outside, [])
        self.assertEqual(captured, [1])
        self.assertEqual(self.access.calls, 6)

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

    def test_idle_scheduler_never_holds_lease_between_collection_windows(self):
        current = datetime.fromtimestamp(NOW, timezone.utc).astimezone(
            __import__('zoneinfo').ZoneInfo('America/Bahia'))
        rules = schedule()
        rule = next(r for r in rules['rules'] if r['weekday'] == (current.weekday()+1)%7)
        rule['enabled'] = True
        rule['times'] = ['00:00' if current.strftime('%H:%M') != '00:00' else '00:01']
        self.provider.shared_schedule = rules
        self.runtime.tick()
        operations = [p['operation'] for p in self.provider.requests]
        self.assertNotIn('lease', operations)
        self.assertNotIn('heartbeat', operations)
        self.runtime._source_blocked = True
        self.runtime.tick()
        self.assertNotIn('lease', [p['operation'] for p in self.provider.requests])

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
        backup.collect()
        self.assertEqual(school['lease']['deviceId'], provider_b.device_id)

        # A selection added while the reserve is collecting must not steal it.
        selected_a[0] = True
        primary.source_ready()
        self.assertEqual(primary.collect()['code'], 'lease-busy')

        # An existing leader that loses its selection yields immediately.
        selected_b[0] = False
        backup.tick()
        self.assertIsNone(school['lease'])
        self.assertIn('release', [r['operation'] for r in provider_b.requests])
        primary.collect()
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
        backup.collect()
        self.assertEqual(school['lease']['deviceId'], provider_b.device_id)

    def test_two_pcs_with_different_shifts_only_matching_pc_takes_school_lease(self):
        # The matutino PC ticks first, but only the vespertino PC has a
        # class matching today's requested shift. Neither its cached selection
        # nor any prior schedule poll is authority to reserve the shared lease.
        school = {'owner': None, 'fence': 0}
        class SharedProvider(Provider):
            def __init__(self, identity):
                super().__init__()
                self.identity = identity

            def storage_binding(self):
                return self.identity, 1

            def frequency_request(self, payload):
                operation = payload['operation']
                if operation == 'status':
                    status = super().frequency_request(payload)
                    status['classes'].append({'classId': 20, 'sourceClassLabel': 'TURMA SINTÉTICA B',
                                              'shift': 'vespertino', 'revision': self.revision})
                    return status
                if operation == 'lease':
                    self.requests.append(copy.deepcopy(payload))
                    if school['owner'] is not None and school['owner'] != self.identity:
                        raise FrequencyError('lease-busy')
                    school['owner'] = self.identity
                    school['fence'] += 1
                    self.fence = school['fence']
                    return {'contractVersion': 2, 'state': 'committed', 'operation': operation,
                            'requestId': payload['requestId'], 'fencingToken': school['fence'],
                            'expiresAt': stamp(self.now + 120)}
                return super().frequency_request(payload)

        def peer(identity, class_id, name, shift):
            provider = SharedProvider(identity)
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            storage = ProtectedStorage(directory.name, crypto=SyntheticCrypto(),
                                       clock=lambda: provider.now)
            storage.bind(identity, 1)
            source = Source()
            source.operational_catalog = lambda st: {
                'selected_class_ids': [class_id], 'unavailable_class_ids': [],
                'catalog': {'classes': [{'class_id': class_id, 'name': name, 'shift': shift}]}}
            view = preview()
            view['snapshot']['class_id'] = class_id
            for student in view['snapshot']['students']:
                student['original_class'] = name
            source.operational_capture = lambda unused: copy.deepcopy(view)
            runtime = FrequencyRuntime(Access(), provider, source,
                                       storage=storage, clock=lambda: provider.now)
            runtime._active = True
            self.addCleanup(runtime.shutdown)
            return runtime, provider

        morning, morning_provider = peer(DEVICE, '13331', 'TURMA SINTÉTICA A', 'matutino')
        evening, evening_provider = peer('22222222-2222-4222-8222-222222222222',
                                         '13332', 'TURMA SINTÉTICA B', 'vespertino')
        morning.tick()  # Idle polling does not claim the school.
        morning.collect({'vespertino'})
        self.assertNotIn('lease', [p['operation'] for p in morning_provider.requests])
        self.assertIsNone(school['owner'])
        self.assertEqual(evening.collect({'vespertino'})['state'], 'ready')
        self.assertEqual(school['owner'], evening_provider.identity)
        self.assertEqual(sum(p['operation'] == 'collect' for p in morning_provider.requests), 0)
        self.assertEqual(sum(p['operation'] == 'collect' for p in evening_provider.requests), 1)

    def test_server_generation_change_cannot_silently_drop_pending_queue(self):
        self.runtime._storage.enqueue({'requestId': 'unreceipted-synthetic'})
        self.provider.storage_binding = lambda: (DEVICE, 2)
        with self.assertRaises(StorageError) as blocked:
            self.runtime.tick()
        self.assertEqual(blocked.exception.code, 'PENDING_BATCHES')
        self.assertEqual(self.runtime._storage._binding, f'{DEVICE}:1')
        self.assertEqual(self.runtime._storage.queue()[0]['payload']['requestId'],
                         'unreceipted-synthetic')
        self.assertNotIn('lease', [p['operation'] for p in self.provider.requests])
        # Once reconciled under the original binding, a safe rotation is allowed.
        self.runtime._storage.acknowledge('unreceipted-synthetic')
        self.runtime._fresh()
        self.assertEqual(self.runtime._storage._binding, f'{DEVICE}:2')

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

    def test_blue_x_goes_as_justified_and_days_off_never_become_absences(self):
        # Owner decision 20/10/2026: the blue X is a justified absence, like the yellow icon; the
        # calendar icon (dia não letivo) and every other non-absence state are never sent as marks.
        source = preview()
        source['snapshot']['records'] = [
            {'source_student_ref': 'row:1', 'date': '2026-02-23', 'lesson': 1, 'state': 'excused_absent', 'source_symbol': 'X:ls-color-info'},
            {'source_student_ref': 'row:1', 'date': '2026-02-23', 'lesson': 2, 'state': 'non_school_day'},
            {'source_student_ref': 'row:1', 'date': '2026-02-23', 'lesson': 3, 'state': 'outside_enrollment'},
            {'source_student_ref': 'row:1', 'date': '2026-02-23', 'lesson': 4, 'state': 'planned_unknown'},
            {'source_student_ref': 'row:1', 'date': '2026-02-23', 'lesson': 5, 'state': 'unmarked'},
        ]
        payload = collection_payload(source, {'class_id': '13331', 'name': 'TURMA SINTÉTICA A'},
                                     {'classId': 10, 'sourceClassLabel': 'TURMA SINTÉTICA A', 'revision': 0}, 99, DEVICE)
        self.assertEqual([(m['slot'], m['mark']) for m in payload['marks']], [(1, 'J')])

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
        self.source.on_capture = lambda: setattr(self.provider, 'now', NOW + frequency_runtime.LEASE_SECONDS + 10)
        self.assertEqual(self.runtime.collect()['state'], 'ready')
        payload = next(p for p in self.provider.requests if p['operation'] == 'collect')
        self.assertEqual(payload['fencingToken'], 3)

    def test_capture_slower_than_lease_is_not_cancelled_by_heartbeat(self):
        class QuickEvent(threading.Event):
            def wait(self, timeout=None): return super().wait(None if timeout is None else min(timeout, 0.02))

        def slow_capture():
            self.provider.now = NOW + frequency_runtime.LEASE_SECONDS + 10  # The grant lapses mid-capture.
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
        self.assertEqual(self.runtime._lease['deadline'], lease_request_started + frequency_runtime.LEASE_SECONDS - 2)
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

    def test_old_uncommitted_fence_is_superseded_by_a_fresh_read_without_anyone(self):
        payload = collection_payload(preview(), {'class_id': '13331', 'name': 'TURMA SINTÉTICA A'},
                                     {'classId': 10, 'sourceClassLabel': 'TURMA SINTÉTICA A', 'revision': 0}, 500, DEVICE)
        self.storage.enqueue(payload)
        result = self.runtime.collect()
        self.assertEqual(result['state'], 'ready')
        self.assertIsNone(result['code'])
        # The server was asked for a receipt first; nothing re-signed or resent.
        self.assertTrue(any(p['operation'] == 'receipt' and p['requestId'] == payload['requestId'] for p in self.provider.requests))
        self.assertFalse(any(p['operation'] == 'collect' and p['requestId'] == payload['requestId'] for p in self.provider.requests))
        self.assertEqual(self.source.reads, 1)  # The class was read again from Smecel.
        self.assertEqual(self.storage.queue(), [])
        self.assertTrue(any(e['kind'] == 'superseded' for e in self.runtime.recent_history(20)))

    def test_old_uncommitted_fence_of_a_class_not_read_now_is_kept(self):
        other = collection_payload(preview(), {'class_id': '13331', 'name': 'TURMA SINTÉTICA A'},
                                   {'classId': 10, 'sourceClassLabel': 'TURMA SINTÉTICA A', 'revision': 0}, 500, DEVICE)
        other.update(sourceClassId='99999', sourceClassLabel='TURMA SINTÉTICA B')  # A class not read in this run.
        self.storage.enqueue(other)
        result = self.runtime.collect()  # Only class A is selected in this run.
        self.assertEqual(result['state'], 'ready')
        self.assertEqual([e['payload']['requestId'] for e in self.storage.queue()], [other['requestId']])
        self.assertFalse(any(e['kind'] == 'superseded' for e in self.runtime.recent_history(20)))

    def test_old_uncommitted_fence_survives_a_failed_re_read(self):
        payload = collection_payload(preview(), {'class_id': '13331', 'name': 'TURMA SINTÉTICA A'},
                                     {'classId': 10, 'sourceClassLabel': 'TURMA SINTÉTICA A', 'revision': 0}, 500, DEVICE)
        self.storage.enqueue(payload)
        self.source.operational_capture = Mock(side_effect=SessionError('expired'))
        result = self.runtime.collect()
        self.assertEqual(result['state'], 'error')
        # Without a confirmed replacement the previous observation stays protected.
        self.assertEqual([e['payload']['requestId'] for e in self.storage.queue()], [payload['requestId']])
        self.assertFalse(any(e['kind'] == 'superseded' for e in self.runtime.recent_history(20)))

    def test_all_classes_with_a_filtered_smecel_list_is_reported_not_called_complete(self):
        self.source.operational_catalog = lambda storage: {
            'selected_class_ids': ['13331'], 'unavailable_class_ids': [], 'all_classes': True,
            'catalog': {'filtered': True, 'classes': [{'class_id': '13331', 'name': 'TURMA SINTÉTICA A', 'shift': 'matutino'}]}}
        result = self.runtime.collect()
        self.assertEqual(self.source.reads, 1)  # The visible class was still sent.
        self.assertEqual(result['code'], 'SOURCE_LIST_FILTERED')

    def test_settings_conflict_preserves_shared_schedule(self):
        before = copy.deepcopy(self.provider.shared_schedule)
        with self.assertRaises(FrequencyError): self.runtime.save_settings(99, schedule())
        self.assertEqual(self.provider.shared_schedule, before)

    def test_fenced_or_conflicting_run_does_not_stop_the_schedule(self):
        for code in ('lease-fenced', 'revision-conflict'):
            self.runtime._code, self.runtime._state = code, 'error'
            zone = __import__('zoneinfo').ZoneInfo('America/Bahia')
            now = datetime.fromtimestamp(self.provider.now, timezone.utc).astimezone(zone)
            value = schedule()
            rule = next(r for r in value['rules'] if r['weekday'] == (now.weekday() + 1) % 7 and r['shift'] == 'matutino')
            rule.update(enabled=True, times=[now.strftime('%H:%M')])
            self.provider.shared_schedule = value
            self.runtime.collect = Mock()
            self.runtime._minute = None
            self.runtime._fired.clear()
            self.runtime.tick()
            import time
            time.sleep(.02)
            self.assertEqual(self.runtime.collect.call_count, 1, code)
            self.provider.now += 3600

    def test_unlinked_class_in_a_shift_alerts_without_blocking(self):
        self.source.operational_catalog = lambda storage: {
            'selected_class_ids': ['13331', '99'], 'unavailable_class_ids': [], 'all_classes': True,
            'catalog': {'classes': [{'class_id': '13331', 'name': 'TURMA SINTÉTICA A', 'shift': 'matutino'},
                                    {'class_id': '99', 'name': 'AEE SEM LIGACAO', 'shift': 'vespertino'}]}}
        result = self.runtime.collect({'vespertino'})  # No linked class in this shift.
        self.assertEqual(result['code'], 'CLASS_RECONCILIATION_REQUIRED')
        self.assertEqual(self.source.reads, 0)
        result = self.runtime.collect({'matutino'})  # The next slot still collects.
        self.assertEqual(self.source.reads, 1)

    def test_shift_without_classes_is_a_quiet_wait(self):
        result = self.runtime.collect({'vespertino'})  # The synthetic class is matutino.
        self.assertEqual((result['code'], result['state']), ('NO_CLASSES_IN_SHIFT', 'reserve'))
        self.assertFalse(any(e['kind'] == 'failure' for e in self.runtime.recent_history(20)))

    def test_connection_blip_reaches_history_only_if_it_lasts(self):
        failures = lambda: [e for e in self.runtime.recent_history(20) if e['kind'] == 'failure']
        self.runtime._error(FrequencyError('ACCESS_UNAVAILABLE'))
        self.provider.now += 300
        self.runtime._error(FrequencyError('ACCESS_UNAVAILABLE'))
        self.assertEqual(failures(), [])  # Healed by the next 30 s check: nothing to show.
        self.provider.now += 301
        self.runtime._error(FrequencyError('ACCESS_UNAVAILABLE'))
        self.runtime._error(FrequencyError('ACCESS_UNAVAILABLE'))
        self.assertEqual([e['code'] for e in failures()], ['ACCESS_UNAVAILABLE'])
        self.runtime._state = 'collecting'  # A run cut short is always explained at once.
        self.runtime._error(FrequencyError('unavailable'))
        self.assertEqual([e['code'] for e in failures()], ['unavailable', 'ACCESS_UNAVAILABLE'])

    def test_paused_run_gets_a_closing_fact(self):
        self.source.on_capture = lambda: self.runtime.local_pause(True)
        self.runtime.collect()
        kinds = [e['kind'] for e in self.runtime.recent_history(20)]
        self.assertIn('collection-started', kinds)
        self.assertIn('collection-stopped', kinds)

    def test_expired_source_login_does_not_loop_or_launch(self):
        self.source.operational_catalog = Mock(side_effect=SessionError('expired'))
        result = self.runtime.collect()
        self.assertEqual(result['state'], 'login-required')
        self.source.operational_catalog.assert_called_once()
        self.assertEqual(self.source.reads, 0)
        self.runtime.collect()
        self.source.operational_catalog.assert_called_once()

    def test_failed_diary_read_is_reported_as_read_failure_and_retried(self):
        self.storage.save_credential('operador@example.invalid', 'SYNTHETIC_ONLY')
        self.source.operational_capture = Mock(side_effect=SessionError('A turma não passou pela revalidação'))
        result = self.runtime.collect()
        self.assertEqual(result['code'], 'SOURCE_READ_FAILED')
        self.assertEqual(result['state'], 'error')
        self.assertFalse(self.runtime._source_blocked)

    def test_status_reports_how_many_classes_are_saved(self):
        self.source.saved_class_count = Mock(return_value=15)
        self.assertEqual(self.runtime.public_status()['selectedClasses'], 15)
        self.source.saved_class_count = Mock(side_effect=OSError())
        self.assertIsNone(self.runtime.public_status()['selectedClasses'])

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

    def test_lesson_days_from_a_real_shaped_diary(self):
        # Owner decision 20/10/2026, end to end inside the collector: real-shaped HTML -> parser ->
        # payload. Every lesson position goes with its day; days off and blanks never count.
        from test_manual_session import raw_fixture
        from coletor.manual_session import captured_preview, source_url
        html = raw_fixture()
        def put(day, lesson, content):
            nonlocal html
            target = f'data-day="{day}" data-lesson="{lesson}"></div>'
            self.assertIn(target, html)
            html = html.replace(target, f'data-day="{day}" data-lesson="{lesson}">{content}</div>', 1)
        point, red = '•', '<strong><span class="ls-color-danger">X</span></strong>'
        # A blue X with its legend replaces the fixture's first original red X (before any injection).
        html = html.replace(red, '<strong><span class="ls-color-info">X</span></strong>', 1)
        for lesson in (1, 2, 4, 5): put(2, lesson, point)          # 02/02: five lessons...
        put(2, 3, red)                                             # ...one of them an absence
        for lesson in range(1, 7): put(3, lesson, '<span class="ls-ico-calendar"></span>')  # 03/02: day off
        put(4, 1, point); put(4, 2, '?')                           # 04/02: a lesson and an unknown mark
        html = html.replace('X = falta não justificada; ', 'X = falta não justificada; '
                            '<span class="ls-color-info"><strong>X</strong></span> = falta com motivo informado (não abona); ', 1)
        result = captured_preview({'url': source_url('13331', 2026), 'password_form': False, 'html': html},
                                  '13331', 2026, allow_partial=True)
        label = result['snapshot']['students'][0]['original_class']
        payload = collection_payload(result, {'class_id': '13331', 'name': label},
                                     {'classId': 10, 'sourceClassLabel': label, 'revision': 0}, 1, DEVICE)
        first = sorted({c['recordKey'] for c in payload['coverage']} | {r['recordKey'] for r in payload['records']})
        key = payload['records'][0]['recordKey']
        days = {c['date']: c for c in payload['coverage'] if c['recordKey'] == key}
        self.assertEqual((days['2026-02-02']['slots'], days['2026-02-02']['complete']), ([1, 2, 3, 4, 5], True))
        self.assertNotIn('2026-02-03', days)                       # the calendar icon is never a lesson
        self.assertEqual((days['2026-02-04']['slots'], days['2026-02-04']['complete']), ([1], False))
        marks = {(m['recordKey'], m['date'], m['slot']): m['mark'] for m in payload['marks']}
        self.assertEqual(marks[(key, '2026-02-02', 3)], 'X')
        self.assertEqual(sorted(marks.values()), ['J', 'X', 'X'])  # the blue X goes as justified
        # The server rejects a mark outside its day's lessons: none may exist.
        lessons = {(c['recordKey'], c['date']): set(c['slots']) for c in payload['coverage']}
        self.assertTrue(all(slot in lessons[(k, d)] for (k, d, slot) in marks))
        self.assertTrue(first)

    def test_an_unknown_smecel_mark_is_logged_once_with_what_it_is(self):
        # Owner request 20/10/2026: one log entry per unknown mark, naming it, never repeated.
        from test_manual_session import raw_fixture
        from coletor.manual_session import captured_preview, source_url
        html = raw_fixture().replace('<strong><span class="ls-color-danger">X</span></strong>',
                                     '<strong><span class="ls-color-danger">?</span></strong>', 1)
        preview = captured_preview({'url': source_url('13331', 2026), 'password_form': False, 'html': html},
                                   '13331', 2026, allow_partial=True)
        self.assertIn('? [ls-color-danger]', {r['source_symbol'] for r in preview['snapshot']['records'] if r['state'] == 'unknown'})
        self.runtime._note_unknown_marks(preview, '6A 2026 - MATUTINO')
        self.runtime._note_unknown_marks(preview, '7B 2026 - MATUTINO')   # same mark elsewhere: not again
        logged = [e for e in self.runtime._history.recent(100) if e['kind'] == 'unknown-mark']
        self.assertEqual([(e['code'], e['label']) for e in logged], [('? [ls-color-danger]', '6A 2026 - MATUTINO')])
        other = {'snapshot': {'records': [{'state': 'unknown', 'source_symbol': '[ls-ico-star]'},
                                          {'state': 'absent', 'source_symbol': 'X'}]}}
        self.runtime._note_unknown_marks(other, '8C 2026 - VESPERTINO')
        self.runtime._note_unknown_marks({'snapshot': {'records': []}}, '9A 2026 - VESPERTINO')
        logged = [e['code'] for e in self.runtime._history.recent(100) if e['kind'] == 'unknown-mark']
        self.assertEqual(sorted(logged), ['? [ls-color-danger]', '[ls-ico-star]'])

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

    def test_heterogeneous_editor_fixture_preserves_scheduled_shift_scope(self):
        value = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/agenda-heterogeneous.json').read_text())
        self.provider.shared_schedule = validate_schedule(value)
        self.runtime.collect = Mock()
        for instant, expected in [('2026-10-19T10:55:00+00:00', {'matutino'}),
                                  ('2026-10-19T15:15:00+00:00', {'matutino'}),
                                  ('2026-10-19T17:10:00+00:00', {'vespertino'}),
                                  ('2026-10-19T21:30:00+00:00', {'vespertino'}),
                                  ('2026-10-20T10:03:00+00:00', {'matutino'})]:
            with self.subTest(instant=instant):
                self.provider.now = datetime.fromisoformat(instant).timestamp()
                self.runtime.collect.reset_mock()
                self.runtime.tick()
                deadline = time.monotonic() + 2
                while self.runtime._operation.locked() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.runtime.collect.assert_called_once_with(expected, _claimed=True)

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

    def test_slot_reached_during_a_long_collection_runs_once_right_after(self):
        zone = __import__('zoneinfo').ZoneInfo('America/Bahia')
        now = datetime.fromtimestamp(NOW, timezone.utc).astimezone(zone)
        later = datetime.fromtimestamp(NOW + 900, timezone.utc).astimezone(zone)
        value = schedule()
        for r in value['rules']: r.update(enabled=False, times=[], recheck=None)
        rule = next(r for r in value['rules'] if r['weekday'] == (now.weekday() + 1) % 7 and r['shift'] == 'matutino')
        rule.update(enabled=True, times=sorted({now.strftime('%H:%M'), later.strftime('%H:%M')}))
        self.provider.shared_schedule = value
        self.runtime.collect = Mock()
        self.runtime.tick()  # First slot: learns the agenda and starts.
        import time
        time.sleep(.02)
        self.assertEqual(self.runtime.collect.call_count, 1)
        self.provider.now += 900
        self.runtime._operation.acquire()  # The first collection is still running.
        self.runtime.tick()
        self.assertEqual(self.runtime.collect.call_count, 1)  # Never in parallel.
        self.runtime._operation.release()
        self.provider.now += 120  # It ends two minutes later: one coalesced run.
        self.runtime.tick()
        time.sleep(.02)
        self.assertEqual(self.runtime.collect.call_count, 2)
        self.provider.now += 60
        self.runtime.tick()
        time.sleep(.02)
        self.assertEqual(self.runtime.collect.call_count, 2)
        self.assertTrue(any(e['kind'] == 'late-start' for e in self.runtime.recent_history(20)))

    def test_delayed_slot_removed_from_the_agenda_meanwhile_is_cancelled(self):
        zone = __import__('zoneinfo').ZoneInfo('America/Bahia')
        now = datetime.fromtimestamp(NOW, timezone.utc).astimezone(zone)
        later = datetime.fromtimestamp(NOW + 900, timezone.utc).astimezone(zone)
        value = schedule()
        for r in value['rules']: r.update(enabled=False, times=[], recheck=None)
        rule = next(r for r in value['rules'] if r['weekday'] == (now.weekday() + 1) % 7 and r['shift'] == 'matutino')
        rule.update(enabled=True, times=sorted({now.strftime('%H:%M'), later.strftime('%H:%M')}))
        self.provider.shared_schedule = value
        self.runtime.collect = Mock()
        self.runtime.tick()
        import time
        time.sleep(.02)
        self.provider.now += 900
        self.runtime._operation.acquire()
        self.runtime.tick()  # The second slot arrives while busy.
        self.runtime._operation.release()
        rule['times'] = [now.strftime('%H:%M')]  # The school removes it meanwhile.
        self.provider.shared_schedule = copy.deepcopy(value)
        self.provider.now += 120
        self.runtime.tick()
        time.sleep(.02)
        self.assertEqual(self.runtime.collect.call_count, 1)
        self.assertTrue(any(e['kind'] == 'late-cancelled' for e in self.runtime.recent_history(20)))

    def test_same_name_twice_keeps_each_card_key_when_the_page_swaps_them(self):
        # 21/10/2026: one student with two enrolments in 7A/8A; the Smecel swapped the two cards
        # between captures and every collection moved all their days from one key to the other.
        source = {'class_id': '13331', 'name': 'TURMA SINTÉTICA A'}
        central = {'classId': 10, 'sourceClassLabel': 'TURMA SINTÉTICA A', 'revision': 0}
        old = [('2026-03-02', 'planned_unknown'), ('2026-05-20', 'absent')]   # first enrolment
        new = [('2026-06-22', 'planned_unknown'), ('2026-10-20', 'excused_absent')]  # current one
        def capture(first, second):
            value = preview()
            value['snapshot']['students'] = [
                {'source_student_ref': ref, 'display_name': 'ALUNO REPETIDO', 'original_class': 'TURMA SINTÉTICA A'}
                for ref in ('row:1', 'row:2')]
            value['snapshot']['records'] = [
                {'source_student_ref': ref, 'date': date, 'lesson': 1, 'state': state}
                for ref, days in (('row:1', first), ('row:2', second)) for date, state in days]
            # Only the ordinal differs between the two cards: an outside-enrolment position is ignored.
            value['snapshot']['records'].append({'source_student_ref': 'row:1', 'date': '2026-01-05',
                                                 'lesson': 1, 'state': 'outside_enrollment'})
            payload = collection_payload(value, source, central, 1, DEVICE)
            return {c['date']: c['recordKey'] for c in payload['coverage']}
        before, after = capture(old, new), capture(new, old)
        self.assertEqual(before, after)
        self.assertNotEqual(before['2026-03-02'], before['2026-06-22'])

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

    def test_a_run_stays_collecting_after_each_class_lease_for_the_progress_bar(self):
        # 21/10/2026: each class renews the lease and that set 'ready', so the window hid its
        # progress bar for the whole run and the heartbeat reported 'ready'.
        seen = []
        def during_capture():
            seen.append(self.runtime.public_status())
            self.runtime._heartbeat(self.runtime._epoch)
        self.source.on_capture = during_capture
        self.assertEqual(self.runtime.collect()['state'], 'ready')
        self.assertEqual(seen[0]['state'], 'collecting')
        self.assertEqual(seen[0]['progress']['total'], 1)
        self.assertTrue(seen[0]['progress']['classLabel'])
        beat = next(r for r in self.provider.requests if r['operation'] == 'heartbeat')
        self.assertEqual(beat['status'], 'collecting')

    def test_a_successful_status_clears_a_stale_no_connection_notice(self):
        # The computer woke up before its network: the notice must not stay until the next time.
        self.runtime._error(AccessDenied('ACCESS_UNAVAILABLE'))
        self.assertEqual(self.runtime.public_status()['code'], 'ACCESS_UNAVAILABLE')
        status = self.runtime.refresh()
        self.assertIsNone(status['code'])
        self.assertEqual(status['state'], 'reserve')

    def test_a_successful_status_keeps_other_alerts(self):
        self.runtime._error(FrequencyError('identity-review'))
        self.assertEqual(self.runtime.refresh()['code'], 'identity-review')

    def test_update_exit_waits_for_the_collection_in_flight_and_starts_none(self):
        # The installer asks the app to quit: the running capture ends normally,
        # never cancelled; nothing new starts while the program is replaced.
        self.runtime._operation.acquire()  # A collection is running.
        finished = []
        waiter = threading.Thread(target=lambda: finished.append(self.runtime.finish_for_exit(5)))
        waiter.start()
        time.sleep(.1)
        self.assertEqual(finished, [])
        self.assertEqual(self.runtime._epoch, 0)  # Not cancelled.
        self.runtime._operation.release()  # The collection ends by itself.
        waiter.join(2)
        self.assertEqual(finished, [True])
        self.runtime._on_started = Mock()
        self.runtime.collect()
        self.runtime._on_started.assert_not_called()
        self.assertFalse(self.runtime._operation.locked())
        self.runtime._fresh = Mock()
        self.runtime.tick()
        self.runtime._fresh.assert_not_called()

    def test_update_exit_gives_up_waiting_after_the_timeout(self):
        self.runtime._operation.acquire()
        try: self.assertFalse(self.runtime.finish_for_exit(.05))
        finally: self.runtime._operation.release()


class LessonsPerDayTests(unittest.TestCase):
    """The Smecel's phantom 6th lesson (owner request 21/10/2026): six positions every day, but the
    6th only happens on some weekdays. Evidence: a whole-day absence that stops before it."""

    @staticmethod
    def day(date, marks=None, lessons=6):
        marks = marks or {}
        return [{'source_student_ref': ref, 'date': date, 'lesson': lesson,
                 'state': {'X': 'absent', 'J': 'excused_absent'}.get(marks.get(ref, {}).get(lesson), 'planned_unknown')}
                for ref in ('row:1', 'row:2') for lesson in range(1, lessons + 1)]

    def records(self):
        five = {lesson: 'X' for lesson in range(1, 6)}
        six = {lesson: 'X' for lesson in range(1, 7)}
        return (self.day('2026-03-02', {'row:1': five})          # Monday, whole day missed: 1..5 only
                + self.day('2026-03-03', {'row:2': six})         # Tuesday, whole day missed: 1..6
                + self.day('2026-03-09')                         # quiet Monday
                + self.day('2026-03-10')                         # quiet Tuesday
                + self.day('2026-03-16', {'row:2': {3: 'J'}})    # Monday, one lesson in the middle
                + self.day('2026-03-14')                         # a school Saturday with no evidence
                + self.day('2026-03-23', {'row:1': {1: 'X', 2: 'X'}}))  # Monday, arrived late

    def test_five_lesson_weekday_loses_only_its_phantom_6th_position(self):
        counts = lessons_per_day(self.records())
        self.assertEqual(counts['2026-03-02'], 5)
        self.assertEqual(counts['2026-03-09'], 5)   # quiet day: its weekday's timetable
        self.assertEqual(counts['2026-03-16'], 5)   # a lone mark on the 3rd never cuts lessons 4 and 5
        self.assertEqual(counts['2026-03-23'], 5)   # missing 1..2 is not a "day ends at 2"
        self.assertIsNone(counts['2026-03-03'])     # Tuesday: the 6th has marks, every position stays
        self.assertIsNone(counts['2026-03-10'])
        self.assertEqual(counts['2026-03-14'], 5)   # no evidence nearby: the class's usual day

    def test_a_mark_on_the_6th_keeps_it_even_on_a_five_lesson_weekday(self):
        records = self.records() + self.day('2026-03-30', {'row:1': {6: 'X'}})
        self.assertIsNone(lessons_per_day(records)['2026-03-30'])

    def test_evidence_is_local_so_a_timetable_change_is_followed(self):
        # Mondays had a 6th lesson in February and stopped in March.
        records = (self.day('2026-02-02', {'row:1': {lesson: 'X' for lesson in range(1, 7)}})
                   + self.day('2026-04-06', {'row:1': {lesson: 'X' for lesson in range(1, 6)}}))
        counts = lessons_per_day(records)
        self.assertIsNone(counts['2026-02-02'])
        self.assertEqual(counts['2026-04-06'], 5)

    def test_a_late_arrival_alone_never_shortens_the_day(self):
        records = self.day('2026-05-04', {'row:1': {1: 'X', 2: 'X'}})
        self.assertIsNone(lessons_per_day(records)['2026-05-04'])

    def test_payload_counts_five_lessons_on_a_quiet_five_lesson_day(self):
        value = preview()
        value['snapshot']['students'] = [
            {'source_student_ref': ref, 'display_name': name, 'original_class': 'TURMA SINTÉTICA A'}
            for ref, name in (('row:1', 'ALUNO UM'), ('row:2', 'ALUNO DOIS'))]
        value['snapshot']['records'] = self.records()
        payload = collection_payload(value, {'class_id': '13331', 'name': 'TURMA SINTÉTICA A'},
                                     {'classId': 10, 'sourceClassLabel': 'TURMA SINTÉTICA A', 'revision': 0}, 1, DEVICE)
        slots = {c['date']: c['slots'] for c in payload['coverage']}
        self.assertEqual(slots['2026-03-09'], [1, 2, 3, 4, 5])
        self.assertEqual(slots['2026-03-10'], [1, 2, 3, 4, 5, 6])
        # Every mark still sits on a lesson of its day (the server rejects any other).
        lessons = {(c['recordKey'], c['date']): set(c['slots']) for c in payload['coverage']}
        self.assertTrue(all(m['slot'] in lessons[(m['recordKey'], m['date'])] for m in payload['marks']))


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
        restored = ProtectedStorage(self.directory.name, crypto=SyntheticCrypto(), clock=lambda: self.now); restored.bind(DEVICE, 1)  # same fixed clock: the real one aged the batches out (21/10/2026)
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

    def test_generation_change_ignores_only_expired_queue_without_mutating_it_preflight(self):
        self.storage.enqueue({'requestId':'expired-synthetic'})
        self.now += 7*86400+1
        # Expiry is checked without writing until the binding transaction can
        # clear the former generation. New device can then be activated.
        self.storage.bind(DEVICE,2)
        self.assertEqual(self.storage.queue(),[])

    def test_future_dated_queue_blocks_generation_switch_instead_of_dropping_data(self):
        self.storage.enqueue({'requestId':'clock-skew-synthetic'})
        self.now -= 120
        with self.assertRaises(StorageError):
            self.storage.bind(DEVICE,2)
        self.assertEqual(self.storage._binding,f'{DEVICE}:1')
        self.now += 120
        self.assertEqual(len(self.storage.queue()),1)

    def test_wrong_device_and_corrupt_dpapi_fail_closed(self):
        self.storage.enable(); self.storage.enqueue({'requestId': DEVICE})
        wrong = ProtectedStorage(self.directory.name, crypto=SyntheticCrypto(), clock=lambda: self.now); wrong.bind('another-device', 1)
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
        every_quarter = [f'{7 + i // 4:02d}:{i % 4 * 15:02d}' for i in range(48)]
        full = schedule(); full['rules'][0]['times'] = every_quarter
        self.assertEqual(len(validate_schedule(full)['rules'][0]['times']), 48)
        invalid = schedule(); invalid['rules'][0]['times'] = every_quarter[:48]; invalid['rules'][0]['recheck'] = '23:30'
        with self.assertRaises(FrequencyError): validate_schedule(invalid)
