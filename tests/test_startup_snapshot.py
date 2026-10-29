"""Instant opening: a non-secret local summary, removed at logout."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from synthetic_access import SyntheticAccess
from coletor.desktop_api import DesktopApi


class StartupSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.api = DesktopApi(self.path, access=SyntheticAccess())

    def status(self, **extra):
        return {'state': 'reserve', 'code': None, 'active': True, 'localPaused': False, 'persistent': True,
                'credential': {'saved': True, 'account': 'op•••@escola.invalid'}, 'selectedClasses': None,
                'classesMode': 'all', 'settings': None, 'lastReceipt': None, 'progress': {}, **extra}

    def test_unpaired_computer_exposes_nothing(self):
        self.api._remember_status(self.status())
        snapshot = self.api.get_startup_snapshot()
        self.assertFalse(snapshot['paired']); self.assertIsNone(snapshot['status']); self.assertEqual(snapshot['history'], [])

    def test_paired_computer_opens_with_last_verified_summary_only(self):
        (self.path / 'device.json').write_text(json.dumps({'state': 'active'}), encoding='utf-8')
        self.api._remember_status(self.status(password='never', secret={'token': 'x'}))
        snapshot = self.api.get_startup_snapshot()
        self.assertTrue(snapshot['paired'])
        # Before the live access check the window only learns that an access exists.
        self.assertEqual(snapshot['status']['credential'], {'saved': True})
        self.assertNotIn('escola.invalid', (self.path / 'ui-snapshot.json').read_text(encoding='utf-8'))
        raw = (self.path / 'ui-snapshot.json').read_text(encoding='utf-8')
        self.assertNotIn('never', raw); self.assertNotIn('token', raw); self.assertNotIn('progress', raw)
        self.assertIn('browser', snapshot['settings'])
        # The program's own version, not the interface package's (owner report 29/10/2026).
        from coletor import __version__
        self.assertEqual(snapshot['version'], __version__)

    def test_snapshot_saved_while_collecting_reopens_safe_and_without_history(self):
        (self.path / 'device.json').write_text(json.dumps({'state': 'active'}), encoding='utf-8')
        self.api._remember_status(self.status(state='collecting'))
        snapshot = self.api.get_startup_snapshot()
        # Never a stale "collecting", always a renderable progress, and the
        # history waits for the verified access (protected endpoint).
        self.assertEqual(snapshot['status']['state'], 'ready')
        self.assertEqual(snapshot['status']['progress'], {'completed': 0, 'total': 0, 'classLabel': None})
        self.assertEqual(snapshot['history'], [])

    def test_logout_forgets_the_summary(self):
        (self.path / 'device.json').write_text(json.dumps({'state': 'active'}), encoding='utf-8')
        self.api._remember_status(self.status())
        self.api._forget_status()
        self.assertIsNone(self.api.get_startup_snapshot()['status'])


if __name__ == '__main__':
    unittest.main()
