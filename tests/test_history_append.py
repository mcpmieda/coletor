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
