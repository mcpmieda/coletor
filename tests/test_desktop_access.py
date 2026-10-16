import tempfile
import unittest
from unittest.mock import Mock
from coletor.desktop_api import DesktopApi
from coletor.institutional_access import AccessDenied
from synthetic_access import SyntheticAccess


class DesktopAccessTests(unittest.TestCase):
    def test_unconfigured_app_blocks_all_protected_operations_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            api = DesktopApi(directory)
            api._manual_session.prepare_login = Mock(side_effect=AssertionError('must not prepare'))
            api._settings.update = Mock(side_effect=AssertionError('must not save'))
            for result in [api.load_demo(), api.preview_html('private-html', '11', 2026),
                           api.prepare_manual_login(2026), api.get_manual_class_selection_preferences(),
                           api.get_local_settings(), api.save_theme('dark'), api.save_schedule({}),
                           api.get_collector_history(), api.save_source_credential('a@escola.invalid', 'x'),
                           api.forget_source_credential(), api.discover_manual_classes(1, True),
                           api.save_manual_class_selection(1, ['11'], 0), api.capture_selected_class(1, '11', True),
                           api.clear_manual_class_selection(1, 0), api.open_manual_session(1, True),
                           api.get_manual_session_status(), api.get_desktop_status(), api.hide_window(), api.set_tray_context({})]:
                self.assertEqual(result['code'], 'ACCESS_REQUIRED')
                self.assertNotIn('private-html', str(result))
            api._manual_session.prepare_login.assert_not_called()
            api._settings.update.assert_not_called()

    def test_renewed_login_or_access_failure_cannot_delete_pending_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            api = DesktopApi(directory, access=SyntheticAccess())
            # Synthetic in-memory queue, no Windows or real student data.
            queue = [{'createdAt': 1791993600, 'payload': {'requestId': 'synthetic-pending'}}]
            api._collector._storage._memory['queue'] = queue
            api._collector._active = True
            api._access_locked()
            self.assertEqual(api._collector._storage._memory.get('queue'), queue)
            self.assertTrue(api._collector.public_status()['active'])
            # An explicit logout can still purge owned local state.
            api._collector.cancel(purge=True)
            self.assertNotIn('queue', api._collector._storage._memory)

    def test_active_collection_close_returns_manual_session_shape_not_collector_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            api = DesktopApi(directory, access=SyntheticAccess())
            api._manual_session.prepare('13331', 2026)
            api._collector._active = True
            result = api.close_manual_session()
            self.assertEqual(result['state'], 'closed')
            self.assertIsNone(result['scope'])
            self.assertIn('generation', result)
            self.assertFalse(result['transmission_enabled'])
            self.assertNotIn('localPaused', result)
            self.assertTrue(api._collector.public_status()['localPaused'])

    def test_ui_state_does_not_bypass_native_gate_and_cleanup_remains_available(self):
        class Denied:
            def run(self, work):
                raise AccessDenied('ACCESS_REQUIRED')
            def status(self):
                return {'authenticated': False, 'authorized': False}
            def logout(self):
                return None
        with tempfile.TemporaryDirectory() as directory:
            api = DesktopApi(directory, access=Denied())
            self.assertEqual(api.load_demo()['code'], 'ACCESS_REQUIRED')
            self.assertFalse(api.get_institutional_access_status()['authorized'])
            self.assertEqual(api.close_manual_session()['state'], 'closed')
            self.assertEqual(api.logout_institutional_access(), {'ok': True})
