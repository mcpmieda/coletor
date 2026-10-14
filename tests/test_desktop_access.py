import tempfile
import unittest
from unittest.mock import Mock
from coletor.desktop_api import DesktopApi
from coletor.institutional_access import AccessDenied


class DesktopAccessTests(unittest.TestCase):
    def test_unconfigured_app_blocks_all_protected_operations_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            api = DesktopApi(directory)
            api._manual_session.prepare_login = Mock(side_effect=AssertionError('must not prepare'))
            api._settings.update = Mock(side_effect=AssertionError('must not save'))
            for result in [api.load_demo(), api.preview_html('private-html', '11', 2026),
                           api.prepare_manual_login(2026), api.get_manual_class_selection_preferences(),
                           api.get_local_settings(), api.save_theme('dark'), api.save_schedule({}),
                           api.save_fox({}), api.discover_manual_classes(1, True),
                           api.save_manual_class_selection(1, ['11'], 0), api.capture_selected_class(1, '11', True)]:
                self.assertEqual(result['code'], 'ACCESS_NOT_CONFIGURED')
                self.assertNotIn('private-html', str(result))
            api._manual_session.prepare_login.assert_not_called()
            api._settings.update.assert_not_called()

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
