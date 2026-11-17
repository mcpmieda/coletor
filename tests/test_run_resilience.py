"""Runs that must survive what the second audit (17/11/2026) found: a pause mid-diary, two agendas in
one minute, a blip before the first class, a reserve computer, a slow network, a wrong clock.

Synthetic classes and students; the access and device layers are the real ones over a counting
transport, so the number and order of requests are the program's own."""
import copy
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import threading
import time
import unittest
from zoneinfo import ZoneInfo

from coletor.device_provider import DeviceProvider, PREFIX, compact, thumbprint, canonical_frequency
from coletor.institutional_access import InstitutionalAccess, AccessDenied, OnlineResponse, OFFICIAL_ORIGIN
from coletor.windows_device_key import WindowsDeviceKey
from coletor.frequency_runtime import FrequencyRuntime
from coletor.protected_storage import ProtectedStorage, StorageError
from coletor.manual_session import SessionError
from coletor.device_provider import FrequencyError
from test_windows_device_key import FakeCrypto

NOW = 1791993600   # fixed synthetic clock
DEVICE = '11111111-1111-4111-8111-111111111111'
def stamp(v): return datetime.fromtimestamp(v, timezone.utc).isoformat()
def schedule():
    return {'timezone': 'America/Bahia', 'rules': [{'weekday': d, 'shift': s, 'enabled': False, 'times': [], 'recheck': None}
            for d in range(7) for s in ['matutino', 'vespertino']]}

class SyntheticCrypto:
    def protect(self, data, entropy): return entropy + b'\0' + bytes(data)
    def unprotect(self, data, entropy):
        if not data.startswith(entropy + b'\0'): raise StorageError()
        return bytes(data[len(entropy) + 1:])

class Server:
    """The Ecossistema's frequency endpoint, synthetic (same shape as tests/test_frequency_runtime.Provider)."""
    def __init__(self, classes):
        self.classes, self.fence, self.results, self.revision = classes, 0, {}, {c: 0 for c in classes}
        self.schedule = schedule(); self.ops = Counter(); self.lease = None
        self.now = lambda: NOW
    def handle(self, payload):
        NOW = self.now()
        op = payload['operation']; self.ops[op] += 1
        if op == 'status':
            return {'contractVersion': 2, 'state': 'ready', 'academicYear': 2026, 'serverTime': stamp(NOW),
                    'classes': [{'classId': i, 'sourceClassLabel': f'TURMA SINTETICA {i}', 'shift': 'matutino', 'revision': self.revision[i]} for i in self.classes],
                    'settings': {'revision': 0, 'paused': False, 'schedule': self.schedule}, 'lease': self.lease}
        if op == 'receipt':
            return {'contractVersion': 2, 'state': 'ready', 'operation': 'receipt', 'requestId': payload['requestId'], 'result': self.results.get(payload['requestId'])}
        r = {'contractVersion': 2, 'state': 'committed', 'operation': op, 'requestId': payload['requestId']}
        if op == 'lease':
            self.fence += 1; r.update(fencingToken=self.fence, expiresAt=stamp(NOW + payload['durationSeconds']), settingsRevision=0)
            self.lease = {'deviceId': DEVICE, 'fencingToken': self.fence, 'expiresAt': stamp(NOW + payload['durationSeconds'])}
        elif op == 'heartbeat': r.update(fencingToken=payload['fencingToken'], expiresAt=stamp(NOW + 100))
        elif op in ('collect', 'collect-unchanged'):
            c = payload['classId']
            r.update(classId=c, revision=self.revision[c] + 1, receivedAt=stamp(NOW), resolvedRecords=1, unresolvedRecords=0, conflicts=0)
            self.revision[c] += 1
        elif op == 'release': r.update(fencingToken=payload['fencingToken'], expiresAt=None); self.lease = None
        elif op == 'incident-collect': r.update(incidents=0, unresolvedStudents=0, changed=False)
        elif op == 'schedule-collect': r.update(classes=[])
        self.results[payload['requestId']] = copy.deepcopy(r)
        return r

class CountingTransport:
    def __init__(self, server, delay=0.0):
        self.calls, self.public, self.completed, self.claimed, self.server, self.delay = Counter(), None, False, False, server, delay
        self.log = []
    def request(self, method, path, value=None):
        suffix = path.removeprefix(PREFIX); self.calls[suffix] += 1
        self.log.append((threading.current_thread().name, suffix, value.get('payload', {}).get('operation') if suffix == 'frequency' else value.get('purpose') if isinstance(value, dict) else None))
        if self.delay: time.sleep(self.delay)
        if suffix == 'config': body = {'contractVersion': 1, 'ready': True, 'serverTime': NOW * 1000}
        elif suffix == 'pairings':
            self.public = value['publicKey']
            body = {'contractVersion': 1, 'id': value['id'], 'pollToken': 'z' * 43, 'displayCode': '123456',
                    'browserUrl': OFFICIAL_ORIGIN + '/frequency-collector/connect?pairing=' + value['id']}
        elif suffix == 'pairings/poll': body = {'contractVersion': 1, 'state': 'completed', 'deviceId': DEVICE}
        elif suffix == 'pairings/claim': self.claimed = True; body = {'claimed': True}
        elif suffix == 'challenge':
            purpose = value['purpose']
            body = {'deviceId': value['deviceId'], 'generation': 1, 'accountKey': 'a' * 43, 'keyThumbprint': thumbprint(self.public),
                    'nonce': 'n' * 43, 'audience': OFFICIAL_ORIGIN, 'method': 'POST',
                    'path': PREFIX + {'collector-access': 'access', 'collector-frequency': 'frequency'}.get(purpose, 'revoke'),
                    'purpose': purpose, 'issuedAt': NOW * 1000, 'expiresAt': NOW * 1000 + 60_000}
            if purpose == 'collector-frequency': body['requestHash'] = value['requestHash']
        elif suffix == 'access':
            body = {'contractVersion': 2, 'authenticated': True, 'authorized': True, 'capability': 'frequency.collector.use',
                    'identityKey': DEVICE + ':synthetic-account', 'checkedAt': stamp(NOW), 'expiresAt': stamp(NOW + 60),
                    'directoryCheckedAt': stamp(NOW), 'directoryValidUntil': stamp(NOW + 300), 'revocationChecked': True}
        elif suffix == 'frequency':
            return OnlineResponse(200, OFFICIAL_ORIGIN + path, canonical_frequency(self.server.handle(value['payload'])))
        else: raise AssertionError(suffix)
        return OnlineResponse(200, OFFICIAL_ORIGIN + path, compact(body))

def preview(i):
    return {'mode': 'manual', 'snapshot': {'source_format': 'smecel-annual-v1', 'snapshot_id': 'a' * 64, 'year': 2026, 'class_id': str(13000 + i),
            'students': [{'source_student_ref': 'row:1', 'display_name': 'ALUNO SINTETICO', 'original_class': f'TURMA SINTETICA {i}'}],
            'records': [{'source_student_ref': 'row:1', 'date': '2026-02-23', 'lesson': 6, 'state': 'absent'},
                        {'source_student_ref': 'row:1', 'date': '2026-02-25', 'lesson': 1, 'state': 'planned_unknown'}]},
            'capture': {'destination': 'local_memory', 'captured_at': stamp(NOW), 'html_sha256': 'b' * 64}}

class Source:
    def __init__(self, classes): self.classes = classes; self.catalogs = 0
    def operational_catalog(self, storage):
        self.catalogs += 1
        return {'selected_class_ids': [str(13000 + i) for i in self.classes], 'unavailable_class_ids': [], 'catalog': {'scope': {'year': 2026},
                'classes': [{'class_id': str(13000 + i), 'name': f'TURMA SINTETICA {i}', 'shift': 'matutino'} for i in self.classes]}}
    def operational_capture(self, class_id): return preview(int(class_id) - 13000)
    def operational_schedule(self): return {}
    def operational_incidents(self, year): return {'complete': True, 'students': []}
    def preserve_and_close(self, storage): pass
    def remember_if_ready(self, storage): pass
    def close(self): pass

def build(n=15, delay=0.0, skew=0):
    tmp = tempfile.TemporaryDirectory()
    classes = list(range(1, n + 1))
    server = Server(classes); transport = CountingTransport(server, delay)
    crypto = FakeCrypto()
    provider = DeviceProvider(Path(tmp.name) / 'dev', transport=transport, key_factory=lambda **kw: WindowsDeviceKey(crypto=crypto, **kw),
                              consent=lambda **kw: True, browser=lambda *a, **k: True, clock=lambda: NOW)
    provider.open_official_login(); provider.verify_online()
    local = lambda: NOW + skew   # This computer's clock; the synthetic Ecossistema keeps NOW.
    access = InstitutionalAccess(provider, clock=local)
    storage = ProtectedStorage(Path(tmp.name) / 'store', crypto=SyntheticCrypto(), consent=lambda: True, clock=local)
    source = Source(classes)
    runtime = FrequencyRuntime(access, provider, source, storage=storage, clock=local)
    return tmp, server, transport, provider, access, storage, source, runtime


ZONE = ZoneInfo('America/Bahia')


def at(hour, minute, second=0):
    """A Monday (16/11/2026) wall time in the school's zone, as a timestamp."""
    return datetime(2026, 11, 16, hour, minute, second, tzinfo=ZONE).timestamp()


class Simple:
    """Access/provider doubles as in tests/test_frequency_runtime.py (no proof layer)."""
    class Access:
        def run(self, work): return work()

    class Provider:
        def __init__(self, server, clock): self.server, self.clock, self.fail = server, clock, None
        def storage_binding(self): return DEVICE, 1
        def frequency_request(self, payload):
            if self.fail and self.fail(payload): raise AccessDenied('ACCESS_UNAVAILABLE')
            reply = self.server.handle(payload)
            if payload['operation'] == 'status': reply['serverTime'] = stamp(self.clock())
            return copy.deepcopy(reply)


def runtime_with(classes=(1, 2, 3), source=None):
    tmp = tempfile.TemporaryDirectory()
    clock = {'now': at(8, 0, 40)}
    server = Server(list(classes)); server.now = lambda: clock['now']
    provider = Simple.Provider(server, lambda: clock['now'])
    storage = ProtectedStorage(Path(tmp.name) / 'store', crypto=SyntheticCrypto(), consent=lambda: True, clock=lambda: clock['now'])
    storage.bind(DEVICE, 1)
    source = source or Source(list(classes))
    runtime = FrequencyRuntime(Simple.Access(), provider, source, storage=storage, clock=lambda: clock['now'])
    runtime._active = True
    return tmp, clock, server, provider, source, runtime


def kinds(runtime): return [e['kind'] for e in reversed(runtime.recent_history(100))]


def wait_idle(runtime, seconds=10):
    deadline = time.time() + seconds
    while runtime._operation.locked() and time.time() < deadline: time.sleep(0.01)


class BlockingSource(Source):
    """operational_capture blocks until close(), then fails as a closed browser does."""
    def __init__(self, classes):
        super().__init__(classes); self.reading, self.closed = threading.Event(), threading.Event()
    def operational_capture(self, class_id):
        self.reading.set()
        self.closed.wait(10)
        raise SessionError('A turma não passou pela revalidação.', 'browser-closed')
    def close(self): self.closed.set()


class RunResilienceTests(unittest.TestCase):
    def test_a_pause_while_a_diary_is_open_is_no_failed_class_and_opens_no_browser(self):
        source = BlockingSource([1, 2, 3])
        tmp, clock, server, provider, source, runtime = runtime_with(source=source)
        self.addCleanup(tmp.cleanup); self.addCleanup(runtime.shutdown)
        worker = threading.Thread(target=runtime.collect); worker.start()
        self.assertTrue(source.reading.wait(5))
        runtime.local_pause(True)                       # The operator pauses while the diary is open.
        worker.join(10)
        self.assertNotIn('class-failed', kinds(runtime))
        self.assertEqual(source.catalogs, 1, 'the Smecel was opened again after the pause')

    def _coinciding(self, first_check_second):
        """A frequency time and a report time in the same minute (08:00); the 30 s check that meets
        them comes `first_check_second` seconds into that minute. Returns the collections started."""
        tmp, clock, server, provider, source, runtime = runtime_with()
        self.addCleanup(tmp.cleanup); self.addCleanup(runtime.shutdown)
        server.schedule['rules'][2].update(enabled=True, times=['08:00'])    # Monday (weekday 1), matutino
        report = {'timezone': 'America/Bahia', 'enabled': True, 'every': 60, 'from': '08:00', 'to': '10:00', 'weekdays': [1]}
        handle = server.handle
        def with_report(payload):
            reply = handle(payload)
            if payload['operation'] == 'status': reply['settings']['reportSchedule'] = report
            return reply
        server.handle = with_report
        gate = threading.Event()
        runtime.collect_report = lambda _claimed=False: gate.wait(10)        # A report that takes a while.
        collected = []
        runtime.collect = lambda shifts=None, _claimed=False, _retry=False: collected.append(sorted(shifts or []))
        start = at(8, 0, first_check_second)
        clock['now'] = start - 60; runtime.tick()                            # 07:59: an ordinary check.
        clock['now'] = start; runtime.tick()                                 # 08:00: both times are due.
        self.assertTrue(runtime._operation.locked(), 'the report did not start')
        clock['now'] = start + 30; runtime.tick()                            # The next check, 30 s later.
        gate.set(); wait_idle(runtime)
        for offset in (60, 90, 120, 150):
            clock['now'] = start + offset; runtime.tick(); wait_idle(runtime)
        return collected, kinds(runtime)

    def test_a_frequency_time_in_the_same_minute_as_a_report_time_is_not_lost(self):
        early = self._coinciding(10)
        late = self._coinciding(40)
        self.assertEqual(late[0], [['matutino']], 'the 08:00 frequency collection never ran')

    def test_a_blip_at_the_start_of_a_scheduled_run_is_asked_again(self):
        tmp, clock, server, provider, source, runtime = runtime_with()
        self.addCleanup(tmp.cleanup); self.addCleanup(runtime.shutdown)
        server.schedule['rules'][2].update(enabled=True, times=['08:00'])
        clock['now'] = at(8, 0, 5)
        seen = {'lease': 0}
        def one_lost_lease(payload):                    # The first concession request gets no answer.
            if payload['operation'] == 'lease':
                seen['lease'] += 1
                return seen['lease'] == 1
            return False
        provider.fail = one_lost_lease
        runtime.tick(); wait_idle(runtime)
        for offset in (30, 60, 90):
            clock['now'] = at(8, 0, 5) + offset; runtime.tick(); wait_idle(runtime)
        self.assertTrue(server.ops.get('collect', 0) == 3 or 'failure' in kinds(runtime),
                        'the 08:00 collection neither ran nor left any line in the history')

    def test_the_reserve_goes_quiet_and_may_update_once_the_other_computer_finished_the_slot(self):
        tmp, clock, server, provider, source, runtime = runtime_with()
        self.addCleanup(tmp.cleanup); self.addCleanup(runtime.shutdown)
        server.schedule['rules'][2].update(enabled=True, times=['08:00'])
        clock['now'] = at(8, 0, 5)
        handle = server.handle
        def other_computer_leads(payload):
            if payload['operation'] == 'lease': raise FrequencyError('lease-busy')
            return handle(payload)
        server.handle = other_computer_leads
        runtime.tick(); wait_idle(runtime)              # This computer is the reserve of the 08:00 slot.
        self.assertIsNotNone(runtime._standby)
        def finished(payload):                          # The other computer sent every class and released.
            reply = handle(payload)
            if payload['operation'] == 'status':
                reply['collections'] = [{'classId': c, 'receivedAt': stamp(at(8, 3))} for c in (1, 2, 3)]
            return reply
        server.handle = finished
        clock['now'] = at(8, 4); runtime.tick(); wait_idle(runtime)
        late = at(8, 30)                                # 30 min after the only time of the day.
        clock['now'] = late
        runtime._status_at = late - 10                  # An answer 10 s old, as right after a check.
        self.assertTrue(runtime._quiet(late), 'still checking the Ecossistema every 30 s, away from the agenda')
        self.assertTrue(runtime.update_allowed(late))

    def test_the_window_thread_never_waits_for_the_network_while_the_collection_is_activated(self):
        tmp, server, transport, provider, access, storage, source, runtime = build(3)
        self.addCleanup(tmp.cleanup); self.addCleanup(runtime.shutdown)
        transport.delay = 0.25                          # 250 ms per HTTPS request.
        worker = threading.Thread(target=runtime.activate); worker.start()
        longest, deadline = 0.0, time.time() + 20
        while worker.is_alive() and time.time() < deadline:   # What the tray's 1 s timer does on the window thread.
            started = time.perf_counter(); runtime.public_status(); longest = max(longest, time.perf_counter() - started)
            time.sleep(0.01)
        worker.join(5); runtime._stop.set()
        self.assertLess(longest, 0.2, 'public_status() waited for the network')

    def test_a_wrong_windows_clock_is_reported_as_the_clock(self):
        for skew in (60, -60):                          # This computer's clock one minute ahead / behind.
            tmp, server, transport, provider, access, storage, source, runtime = build(3, skew=skew)
            self.addCleanup(tmp.cleanup); self.addCleanup(runtime.shutdown)
            runtime._active = True
            alerts = []
            runtime._on_alert = alerts.append
            try: runtime.tick()
            except Exception as error: runtime._error(error)      # What the scheduler loop does.
            status = runtime.public_status()
            with self.subTest(skew=skew):
                self.assertEqual(status['code'], 'CLOCK_OUT_OF_SYNC')


if __name__ == '__main__':
    unittest.main(verbosity=2)
