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
        self.assertFalse(self.storage.quarantine_unreadable_queue())  # One failure is not enough.
        self.now += 601
        self.assertTrue(self.storage.quarantine_unreadable_queue())
        self.assertFalse((self.storage.directory / 'queue.dpapi').exists())
        kept = list(self.storage.directory.glob('queue-unreadable-*.dpapi'))
        self.assertEqual([p.read_bytes() for p in kept], [old])
        self.assertEqual(self.storage.queue(), [])
        self.assertFalse(self.storage.quarantine_unreadable_queue())

    def test_a_momentary_failure_never_sets_the_queue_aside(self):
        self.storage.bind('device', 1); self.storage._enabled = True
        self.storage.enqueue({'requestId': 'CURRENT'})
        crypto = self.storage._crypto
        failing = type('Failing', (), {'protect': crypto.protect,
                                        'unprotect': lambda *_: (_ for _ in ()).throw(OSError('DPAPI busy'))})()
        self.storage._crypto = failing
        self.assertFalse(self.storage.quarantine_unreadable_queue())
        self.storage._crypto = crypto  # DPAPI is back before the grace period ends.
        self.now += 601
        self.assertFalse(self.storage.quarantine_unreadable_queue())
        self.assertEqual(len(self.storage.queue()), 1)

    def test_logout_clear_removes_set_aside_queues(self):
        self.storage.directory.mkdir(parents=True, exist_ok=True)
        (self.storage.directory / 'queue-unreadable-20261019-080000.dpapi').write_bytes(b'CFV2-old')
        self.storage.clear()
        self.assertEqual(list(self.storage.directory.glob('queue-unreadable-*.dpapi')), [])

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


class CredentialSummaryCacheTests(unittest.TestCase):
    def test_masked_account_is_decrypted_once_and_follows_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            crypto = SyntheticCrypto()
            calls = []
            original = crypto.unprotect
            crypto.unprotect = lambda *a: (calls.append(1), original(*a))[1]
            storage = ProtectedStorage(Path(directory), crypto=crypto, clock=lambda: 1_800_000_000.0)
            storage.bind('device', 1); storage._enabled = True
            storage.save_credential('operador@escola.invalid', 'synthetic')
            self.assertEqual(storage.credential_status()['account'], 'op•••@escola.invalid')
            before = len(calls)
            for _ in range(5): storage.credential_status()
            self.assertEqual(len(calls), before)  # Served from the cache.
            storage.clear_credential()
            self.assertEqual(storage.credential_status(), {'saved': False})
