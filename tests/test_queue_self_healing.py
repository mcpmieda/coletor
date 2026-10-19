"""The local queue heals itself while the computer is authorized."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from coletor.protected_storage import ProtectedStorage, RETENTION_SECONDS
from test_frequency_runtime import SyntheticCrypto


class QueueSelfHealingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.now = 1_800_000_000.0
        self.storage = ProtectedStorage(Path(self.temp.name), crypto=SyntheticCrypto(), clock=lambda: self.now)

    def test_unopened_queue_is_reported_as_waiting_not_as_a_problem(self):
        self.storage.bind('device', 1); self.storage._enabled = True
        self.storage.enqueue({'requestId': 'SYNTHETIC'})
        self.storage._binding = None  # New process, before the live access opens it.
        info = self.storage.recovery_status()
        self.assertTrue(info['pending']); self.assertFalse(info['bound'])

    def test_queue_of_an_older_generation_is_set_aside_kept_and_reported(self):
        self.storage.bind('device', 1); self.storage._enabled = True
        self.storage.enqueue({'requestId': 'OLD_GENERATION'})
        old = (self.storage.directory / 'queue.dpapi').read_bytes()
        self.storage._binding = None
        self.storage.bind('device', 2)  # Live access, newer generation: cannot decrypt it.
        self.assertTrue(self.storage.quarantine_unreadable_queue())
        self.assertFalse((self.storage.directory / 'queue.dpapi').exists())
        kept = list(self.storage.directory.glob('queue-unreadable-*.dpapi'))
        self.assertEqual([p.read_bytes() for p in kept], [old])
        self.assertEqual(self.storage.queue(), [])
        self.assertFalse(self.storage.quarantine_unreadable_queue())

    def test_readable_queue_is_never_set_aside(self):
        self.storage.bind('device', 1); self.storage._enabled = True
        self.storage.enqueue({'requestId': 'CURRENT'})
        self.assertFalse(self.storage.quarantine_unreadable_queue())
        self.assertEqual(len(self.storage.queue()), 1)

    def test_expired_unreceipted_batches_are_counted_not_silent(self):
        self.storage.bind('device', 1); self.storage._enabled = True
        self.storage.enqueue({'requestId': 'OLD'})
        self.now += RETENTION_SECONDS + 1
        self.assertEqual(self.storage.queue(), [])
        self.assertEqual(self.storage.take_expired(), 1)
        self.assertEqual(self.storage.take_expired(), 0)


if __name__ == '__main__':
    unittest.main()
