"""The weekly grid goes only when it changed, or once a day (owner decision 22/10/2026)."""
import copy
import tempfile
import unittest

from coletor.device_provider import FrequencyError
from coletor.frequency_runtime import FrequencyRuntime
from coletor.local_copy import schedule_hash
from coletor.manual_session import SessionError
from coletor.protected_storage import ProtectedStorage

from test_frequency_runtime import DEVICE, Access, Source, SyntheticCrypto
from test_unchanged_delivery import CopyProvider

LESSONS = [{'weekday': 1, 'slot': 1, 'subject': 'DISCIPLINA UM'}, {'weekday': 2, 'slot': 3, 'subject': 'PRÁTICA SINTÉTICA'}]


class ScheduleProvider(CopyProvider):
    """The fake Ecossistema also answers schedule-collect, like service-v2's collectSchedule."""
    def __init__(self):
        super().__init__()
        self.grids_held = {}  # The grid hash the server keeps per class.
        self.reject = None

    def frequency_request(self, payload):
        if payload['operation'] != 'schedule-collect':
            return super().frequency_request(payload)
        self.requests.append(copy.deepcopy(payload))
        if payload['fencingToken'] != self.fence: raise FrequencyError('lease-fenced')
        if self.reject: raise FrequencyError(self.reject)
        classes = []
        for item in payload['classes']:
            digest = schedule_hash(item)
            classes.append({'classId': item['classId'], 'changed': self.grids_held.get(item['classId']) != digest})
            self.grids_held[item['classId']] = digest
        result = {'contractVersion': 2, 'state': 'committed', 'operation': 'schedule-collect',
                  'requestId': payload['requestId'], 'classes': classes}
        self.results[payload['requestId']] = copy.deepcopy(result)
        return result


class GridSource(Source):
    def __init__(self):
        super().__init__()
        self.grid_reads = 0
        self.fail = False
        # 13331 is the selected class (Centro class 10); 55555 is on the grid but not in the Centro.
        self.grids = {'13331': {'title': 'TURMA SINTÉTICA A', 'lessons': copy.deepcopy(LESSONS)},
                      '55555': {'title': 'TURMA SEM CENTRO', 'lessons': copy.deepcopy(LESSONS)}}

    def operational_catalog(self, storage):
        value = super().operational_catalog(storage)
        value['catalog']['classes'].append({'class_id': '55555', 'name': 'TURMA SEM CENTRO', 'shift': 'matutino'})
        return value

    def operational_schedule(self):
        self.grid_reads += 1
        if self.fail: raise SessionError('SOURCE_READ_FAILED')
        return copy.deepcopy(self.grids)


class ScheduleDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.provider, self.access, self.source = ScheduleProvider(), Access(), GridSource()
        self.storage = ProtectedStorage(self.directory.name, crypto=SyntheticCrypto(), consent=lambda: True,
                                        clock=lambda: self.provider.now)
        self.storage.bind(DEVICE, 1)
        self.storage.enable()
        self.runtime = FrequencyRuntime(self.access, self.provider, self.source, storage=self.storage,
                                        clock=lambda: self.provider.now)
        self.runtime._active = True
        self.addCleanup(self.runtime.shutdown)

    def run_once(self, after=0):
        self.provider.now += after
        start = len(self.provider.requests)
        result = self.runtime.collect()
        self.assertEqual(result['state'], 'ready', repr(result))
        return [r for r in self.provider.requests[start:] if r['operation'] == 'schedule-collect']

    def history(self, kind):
        return [e for e in self.runtime.recent_history(50) if e['kind'] == kind]

    def test_the_grid_goes_with_the_centro_class_and_only_for_known_classes(self):
        sent = self.run_once()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['classes'], [{'classId': 10, 'sourceClassId': '13331',
                                               'sourceClassLabel': 'TURMA SINTÉTICA A', 'lessons': LESSONS}])
        self.assertEqual(sent[0]['fencingToken'], self.provider.fence)
        self.assertTrue(sent[0]['sourceVersion'].startswith('sha256:'))
        self.assertEqual(self.history('schedule-sent')[0]['sent'], 1)
        # The local copy is encrypted: no subject on disk.
        path = self.storage.directory / 'copy-schedule.dpapi'
        self.assertNotIn('DISCIPLINA'.encode(), path.read_bytes())

    def test_an_unchanged_grid_is_read_at_most_hourly_and_sent_once_a_day(self):
        self.run_once()
        self.assertEqual(self.run_once(after=1800), [])
        self.assertEqual(self.source.grid_reads, 1)  # Not even read within the hour.
        self.assertEqual(self.run_once(after=1800), [])
        self.assertEqual(self.source.grid_reads, 2)  # Read, same grid, not sent.
        self.assertEqual(len(self.run_once(after=24 * 3600)), 1)  # A new day: sent again.

    def test_a_changed_grid_goes_at_the_next_hourly_read(self):
        self.run_once()
        self.source.grids['13331']['lessons'][0]['subject'] = 'DISCIPLINA DOIS'
        self.assertEqual(self.run_once(after=600), [])
        sent = self.run_once(after=3000)
        self.assertEqual(sent[0]['classes'][0]['lessons'][0]['subject'], 'DISCIPLINA DOIS')
        self.assertEqual(self.history('schedule-sent')[0]['sent'], 1)

    def test_a_grid_that_cannot_be_read_never_fails_the_run_and_is_tried_again(self):
        self.source.fail = True
        self.assertEqual(self.run_once(), [])
        self.assertEqual(self.history('failure')[0]['label'], 'Grade de horários')
        self.assertEqual(self.provider.revision, 1)  # The diary went anyway.
        self.source.fail = False
        self.assertEqual(len(self.run_once(after=60)), 1)  # No hourly wait after a failed read.

    def test_a_grid_the_server_refuses_keeps_no_copy_and_goes_again(self):
        self.provider.reject = 'source-invalid'
        self.assertEqual(len(self.run_once()), 1)
        self.assertEqual(self.history('failure')[0]['code'], 'source-invalid')
        self.assertIsNone(self.storage.load_copy('schedule'))
        self.provider.reject = None
        self.assertEqual(len(self.run_once(after=3600)), 1)
        self.assertIsNotNone(self.storage.load_copy('schedule'))

    def test_a_lost_copy_sends_the_grid_again(self):
        self.run_once()
        (self.storage.directory / 'copy-schedule.dpapi').unlink()  # As after formatting the computer.
        self.assertEqual(len(self.run_once(after=3600)), 1)
        self.assertEqual(self.history('schedule-sent')[0]['sent'], 0)  # The server already had it.

    def test_a_school_pause_found_before_sending_stops_the_run(self):
        self.source.operational_schedule = lambda: (setattr(self.provider, 'paused', True), self.source.grids)[1]
        self.runtime.collect()
        self.assertEqual([r for r in self.provider.requests if r['operation'] == 'schedule-collect'], [])
        self.assertFalse(self.history('schedule-sent'))

    def test_lost_access_while_reading_the_grid_stops_the_run(self):
        self.source.operational_schedule = lambda: (setattr(self.access, 'denied', True), self.source.grids)[1]
        self.assertNotEqual(self.runtime.collect()['state'], 'ready')
        self.assertEqual([r for r in self.provider.requests if r['operation'] == 'schedule-collect'], [])
        self.assertFalse([e for e in self.history('failure') if e.get('label') == 'Grade de horários'])


if __name__ == '__main__':
    unittest.main()
