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
