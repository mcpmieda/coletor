"""A class's diary goes whole only when it changed (owner decision 22/10/2026)."""
import copy
import tempfile
import unittest

from coletor.device_provider import FrequencyError
from coletor.frequency_runtime import FrequencyRuntime
from coletor.local_copy import content_hash
from coletor.protected_storage import ProtectedStorage

from test_frequency_runtime import DEVICE, Access, Provider, Source, SyntheticCrypto, preview


class CopyProvider(Provider):
    """The fake Ecossistema also answers the short message, like service-v2's collectUnchanged."""
    def __init__(self):
        super().__init__()
        self.held = None  # The content hash of the class's last whole diary.
        self.forget = False  # As after a restore: nothing it can confirm.

    def frequency_request(self, payload):
        if payload['operation'] == 'collect':
            result = super().frequency_request(payload)
            self.held = content_hash(payload)
            return result
        if payload['operation'] != 'collect-unchanged':
            return super().frequency_request(payload)
        self.requests.append(copy.deepcopy(payload))
        if payload['fencingToken'] != self.fence: raise FrequencyError('lease-fenced')
        if payload['expectedRevision'] != self.revision: raise FrequencyError('revision-conflict')
        if self.forget or payload['contentHash'] != self.held: raise FrequencyError('payload-required')
        self.revision += 1
        result = {'contractVersion': 2, 'state': 'committed', 'operation': 'collect-unchanged',
                  'requestId': payload['requestId'], 'classId': payload['classId'], 'revision': self.revision,
                  'receivedAt': payload['observedAt'], 'resolvedRecords': 1, 'unresolvedRecords': 0, 'conflicts': 0}
        self.results[payload['requestId']] = copy.deepcopy(result)
        return result


class UnchangedDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.provider, self.access, self.source = CopyProvider(), Access(), Source()
        self.storage = ProtectedStorage(self.directory.name, crypto=SyntheticCrypto(), consent=lambda: True,
                                        clock=lambda: self.provider.now)
        self.storage.bind(DEVICE, 1)
        self.storage.enable()
        self.runtime = FrequencyRuntime(self.access, self.provider, self.source, storage=self.storage,
                                        clock=lambda: self.provider.now)
        self.runtime._active = True
        self.addCleanup(self.runtime.shutdown)

    def run_once(self):
        start = len(self.provider.requests)
        result = self.runtime.collect()
        self.assertEqual(result['state'], 'ready', repr(result))
        return [r['operation'] for r in self.provider.requests[start:] if r['operation'].startswith('collect')]

    def test_first_send_is_whole_and_an_unchanged_diary_then_sends_only_the_short_message(self):
        self.assertEqual(self.run_once(), ['collect'])
        self.provider.now += 3600
        self.assertEqual(self.run_once(), ['collect-unchanged'])
        brief = next(r for r in reversed(self.provider.requests) if r['operation'] == 'collect-unchanged')
        self.assertNotIn('coverage', brief)
        self.assertNotIn('marks', brief)
        self.assertEqual(brief['records'][0]['originalName'], 'ALUNO SINTÉTICO')
        # Nothing waits in the protected queue, and the receipt still shows on the window.
        self.assertEqual(self.storage.queue(), [])
        self.assertEqual(self.runtime.public_status()['lastReceipt']['resolvedRecords'], 1)

    def test_what_the_server_cannot_confirm_goes_whole_in_the_same_run(self):
        self.run_once()
        self.provider.now += 3600
        self.provider.forget = True
        self.assertEqual(self.run_once(), ['collect-unchanged', 'collect'])
        self.assertEqual(self.storage.queue(), [])

    def test_a_changed_diary_goes_whole(self):
        self.run_once()
        self.provider.now += 3600
        changed = preview()
        changed['snapshot']['records'][2]['state'] = 'absent'
        self.source.operational_capture = lambda class_id: changed
        self.assertEqual(self.run_once(), ['collect'])

    def test_each_class_still_goes_whole_once_a_day(self):
        self.run_once()
        self.provider.now += 24 * 3600
        self.assertEqual(self.run_once(), ['collect'])
        self.provider.now += 3600
        self.assertEqual(self.run_once(), ['collect-unchanged'])

    def test_a_lost_or_unreadable_copy_means_a_whole_diary_and_a_new_copy(self):
        self.run_once()
        path = self.storage.directory / 'copy-frequency-13331.dpapi'
        self.assertTrue(path.exists())
        # The copy is encrypted: no student name or mark on disk.
        self.assertNotIn('ALUNO'.encode(), path.read_bytes())
        path.write_bytes(b'CFV2\0garbage')  # As after a restore or another Windows user.
        self.provider.now += 3600
        self.assertEqual(self.run_once(), ['collect'])
        self.assertEqual(self.storage.load_copy('frequency-13331')['contentHash'], self.provider.held)
        path.unlink()  # As after formatting the computer.
        self.provider.now += 3600
        self.assertEqual(self.run_once(), ['collect'])
        self.assertTrue(path.exists())

    def test_logout_or_a_new_device_generation_forgets_the_copies(self):
        self.run_once()
        self.storage.clear()
        self.assertFalse(any(self.storage.directory.glob('copy-*.dpapi')))
        self.storage.bind(DEVICE, 1)
        self.storage.enable()
        self.provider.now += 3600
        self.assertEqual(self.run_once(), ['collect'])


if __name__ == '__main__':
    unittest.main()
