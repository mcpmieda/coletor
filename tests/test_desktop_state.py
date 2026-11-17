from synthetic_access import SyntheticAccess
"""Portable contracts for truthful local tray state; not native Windows proof."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from coletor.desktop_api import DesktopApi
from coletor.desktop_state import DesktopState
from coletor.desktop import centered_window_geometry, window_profile
from coletor.local_settings import LocalSettings, default_settings


class NativeWindowGeometryTests(unittest.TestCase):
    def test_primary_monitor_work_area_is_centered_and_avoids_taskbar(self):
        area = (-1920, 20, 0, 1040)
        bounds = centered_window_geometry(area)
        self.assertEqual(bounds, {'width': 1240, 'height': 820,
                                  'x': -1580, 'y': 120, 'min_size': (900, 620)})
        self.assertEqual(bounds['x'] + bounds['width'] // 2, -960)
        self.assertEqual(bounds['y'] + bounds['height'] // 2, 530)

    def test_small_screen_fits_inside_work_area_without_offscreen_minimum(self):
        bounds = centered_window_geometry((0, 0, 800, 600))
        self.assertEqual(bounds, {'width': 768, 'height': 568,
                                  'x': 16, 'y': 16, 'min_size': (768, 568)})

    def test_invalid_display_size_fails_before_native_window(self):
        with self.assertRaises(ValueError):
            centered_window_geometry((5, 0, 5, 100))


class WindowProfileTests(unittest.TestCase):
    def test_the_window_profile_is_a_new_folder_of_the_coletor_and_earlier_ones_are_removed(self):
        # pywebview's private mode left a folder in %TEMP% at each closing WebView2 was slow to leave.
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "collector-history.jsonl").write_text("kept", encoding="utf-8")
            first = Path(window_profile(directory))
            (first / "EBWebView" / "Default").mkdir(parents=True)
            (first / "EBWebView" / "Default" / "Cookies").write_bytes(b"left by the last opening")
            second = Path(window_profile(directory))
            self.assertEqual((first.parent, second.parent), (Path(directory) / "janela",) * 2)
            self.assertNotEqual(first, second)  # Never shared with a browser still leaving.
            self.assertEqual([p.name for p in second.parent.iterdir()], [second.name])
            self.assertEqual(list(second.iterdir()), [])
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ["collector-history.jsonl", "janela"])

    @unittest.skipUnless(__import__("os").name == "nt", "Windows keeps an open file from being deleted")
    def test_a_profile_still_held_stays_until_a_later_opening_and_never_stops_this_one(self):
        with tempfile.TemporaryDirectory() as directory:
            leaving = Path(window_profile(directory))
            with (leaving / "lockfile").open("wb"):
                opened = Path(window_profile(directory))
                self.assertTrue(leaving.exists() and opened.is_dir() and opened != leaving)
            self.assertEqual([p.name for p in Path(window_profile(directory)).parent.iterdir() if p.name == leaving.name], [])


class DesktopStateTests(unittest.TestCase):
    def test_real_read_cannot_be_cleared_by_ui_or_overlapping_operation(self):
        state = DesktopState(default_settings()["fox"])
        state.begin_read(); state.begin_read()
        state.set_context("idle", False)
        self.assertEqual(state.snapshot()["activity"], "reading")
        state.end_read(True)
        self.assertEqual(state.snapshot()["activity"], "reading")
        state.end_read(True)
        self.assertEqual(state.snapshot()["activity"], "error")
        state.set_context("idle", False)
        self.assertEqual(state.snapshot()["activity"], "idle")

    def test_system_motion_setting_animates_before_the_window_reports(self):
        self.assertFalse(DesktopState(default_settings()["fox"], reduced_motion=False).snapshot()["reduced_motion"])
        self.assertTrue(DesktopState(default_settings()["fox"], reduced_motion=None).snapshot()["reduced_motion"])

    def test_no_collection_state_or_arbitrary_details_are_accepted(self):
        state = DesktopState(default_settings()["fox"])
        for activity, reduced in [("collected", False), ("DO_NOT_ECHO", False), ([], False), ("idle", 0)]:
            with self.assertRaises(ValueError): state.set_context(activity, reduced)
        self.assertTrue(state.snapshot()["reduced_motion"])
        before = state.snapshot()
        with self.assertRaises(ValueError):
            state.set_fox({"version": 1, "show": True, "animate": True, "token": "DO_NOT_STORE"})
        self.assertEqual(state.snapshot(), before)

    def test_bridge_activity_is_tied_to_actual_preview_and_resets_on_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            api = DesktopApi(Path(directory) / "isolated", access=SyntheticAccess())
            states = []
            api._desktop_state._changed = lambda: states.append(api._desktop_state.snapshot()["activity"])
            result = api.load_demo()
            self.assertIn("snapshot", result)
            self.assertEqual(states, ["reading", "idle"])
            states.clear()
            with patch("coletor.service.preview", side_effect=RuntimeError("DO_NOT_ECHO")):
                with self.assertRaises(RuntimeError): api.load_demo()
            self.assertEqual(states, ["reading", "error"])
            self.assertFalse((Path(directory) / "isolated").exists())
            self.assertFalse(api.get_desktop_status()["tray_available"])
            self.assertIn("error", api.hide_window())
            self.assertIn("error", api.set_tray_context("collected", False))

    def test_fox_is_always_shown_even_with_an_old_hidden_preference(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalSettings(Path(directory))
            store.update("fox", {"version": 1, "show": False, "animate": False})
            api = DesktopApi(Path(directory), access=SyntheticAccess())
            self.assertEqual(api._desktop_state.snapshot()["fox"], {"version": 1, "show": True, "animate": True})
            self.assertFalse(hasattr(api, "save_fox"))
