"""History grows by appending one line per event and compacts past the limit."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from coletor import history as module
from coletor.history import CollectorHistory


class HistoryAppendTests(unittest.TestCase):
    def test_appends_without_rewriting_and_compacts_past_the_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1_800_000_000.0]
            log = CollectorHistory(directory, clock=lambda: now[0])
            for i in range(module.MAX_ENTRIES + module.COMPACT_SLACK - 1):
                now[0] += 1; log.record('class-sent', label=f'T{i}', sent=1)
            lines = log.path.read_text(encoding='utf-8').count('\n')
            self.assertEqual(lines, module.MAX_ENTRIES + module.COMPACT_SLACK - 1)  # Appended only.
            now[0] += 1; log.record('collection-finished')
            now[0] += 1; log.record('collection-finished')
            lines = log.path.read_text(encoding='utf-8').count('\n')
            self.assertLessEqual(lines, module.MAX_ENTRIES + 1)  # Compacted once.
            self.assertEqual(log.recent(1)[0]['kind'], 'collection-finished')

    def test_an_oversized_file_is_read_from_its_end(self):
        # Long incident notices can pass the read limit before the line count asks for a rewrite:
        # the newest events are the ones read (the start used to be), and a rewrite keeps them.
        with tempfile.TemporaryDirectory() as directory:
            now = [1_800_000_000.0]
            log = CollectorHistory(directory, clock=lambda: now[0])
            notices = [{'name': 'ALUNA SINTETICA ' + 'X' * 100, 'classLabel': '6A', 'incident': '1',
                        'reason': 'motivo sintetico ' + 'y' * 140, 'sent': False}] * module.MAX_NOTICES
            lines = 0
            while not lines or log.path.stat().st_size <= module.MAX_READ_BYTES:
                now[0] += 1; lines += 1
                log.record('incidents-sent', sent=lines, notices=notices)
            self.assertLess(lines, module.MAX_ENTRIES)
            now[0] += 1; log.record('collection-finished')
            newest = log.recent(3)
            self.assertEqual([e['kind'] for e in newest], ['collection-finished', 'incidents-sent', 'incidents-sent'])
            self.assertEqual(newest[1]['sent'], lines)
            # A new opening counts the lines it can read and goes on appending after the newest.
            again = CollectorHistory(directory, clock=lambda: now[0])
            now[0] += 1; again.record('activated')
            self.assertEqual([e['kind'] for e in again.recent(2)], ['activated', 'collection-finished'])

    def test_survives_a_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            CollectorHistory(directory).record('started')
            log = CollectorHistory(directory)
            log.record('activated')
            self.assertEqual([e['kind'] for e in log.recent(5)], ['activated', 'started'])


if __name__ == '__main__':
    unittest.main()


class HistoryCursorAndRetentionTests(unittest.TestCase):
    def test_same_millisecond_events_get_distinct_increasing_times(self):
        with tempfile.TemporaryDirectory() as directory:
            log = CollectorHistory(directory, clock=lambda: 1_800_000_000.0)
            log.record('collection-started')
            newest = log.recent(1)[0]['at']
            log.record('collection-finished')  # Same millisecond.
            after = [e for e in log.recent(10) if e['at'] > newest]
            self.assertEqual([e['kind'] for e in after], ['collection-finished'])

    def test_retention_rewrites_the_file_at_most_hourly_not_at_every_event(self):
        # With 30 days in the file each new event pushed an old one past the retention and rewrote
        # the whole file: 59 rewrites for the 60 events of a day.
        with tempfile.TemporaryDirectory() as directory:
            now = [1_800_000_000.0]
            log = CollectorHistory(directory, clock=lambda: now[0])
            for hour in range(30 * 24):
                now[0] += 3600; log.record('class-sent', label='TURMA SINTETICA', sent=1)
            rewrites, replace = [], module.os.replace
            self.addCleanup(setattr, module.os, 'replace', replace)
            module.os.replace = lambda source, target: (rewrites.append(1), replace(source, target))[1]
            for _ in range(60):  # One run: an event a minute.
                now[0] += 60; log.record('class-sent', label='TURMA SINTETICA', sent=1)
            self.assertLessEqual(len(rewrites), 2)
            self.assertEqual(log.recent(1)[0]['kind'], 'class-sent')
            # What the window lists never includes a fact past the retention, rewritten or not.
            self.assertTrue(all(entry['at'] >= now[0] - module.RETENTION_SECONDS for entry in log.recent(module.MAX_ENTRIES)))

    def test_facts_older_than_30_days_leave_the_file_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1_800_000_000.0]
            log = CollectorHistory(directory, clock=lambda: now[0])
            for kind in ('started', 'activated', 'collection-started'):
                log.record(kind)
            now[0] += module.RETENTION_SECONDS + 86_400
            CollectorHistory(directory, clock=lambda: now[0]).record('resumed')  # After a restart.
            physical = log.path.read_text(encoding='utf-8')
            self.assertNotIn('collection-started', physical)
            self.assertIn('resumed', physical)
