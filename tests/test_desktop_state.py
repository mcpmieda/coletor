"""Portable contracts for truthful local tray state; not native Windows proof."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from coletor.desktop_api import DesktopApi
from coletor.desktop_state import DesktopState
from coletor.local_settings import LocalSettings, default_settings


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
            api = DesktopApi(Path(directory) / "isolated")
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

    def test_saved_fox_controls_tray_and_failed_save_keeps_previous_preference(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalSettings(Path(directory))
            store.update("fox", {"version": 1, "show": False, "animate": False})
            api = DesktopApi(Path(directory))
            self.assertFalse(api._desktop_state.snapshot()["fox"]["show"])
            with patch.object(api._settings, "update", side_effect=OSError("DO_NOT_ECHO")):
                self.assertIn("error", api.save_fox({"version": 1, "show": True, "animate": True}))
            self.assertFalse(api._desktop_state.snapshot()["fox"]["show"])
            self.assertIn("settings", api.save_fox({"version": 1, "show": True, "animate": True}))
            self.assertTrue(api._desktop_state.snapshot()["fox"]["animate"])
