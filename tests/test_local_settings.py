from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from coletor.desktop_api import DesktopApi
from coletor.local_settings import LocalSettings, default_settings, user_settings_directory

ROOT = Path(__file__).resolve().parents[1]


def schedule():
    presets = json.loads((ROOT / "ui/src/schedule-presets.json").read_text(encoding="utf-8"))
    return {"schemaVersion": 1, "scope": "school", "storageMode": "local-preview", "localRevision": 1,
            "sharedRevision": None, "timezone": "America/Bahia", "rules": presets["rules"]}


class LocalSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "ColetorFrequenciaSmecel"
        self.store = LocalSettings(self.directory)

    def test_read_defaults_does_not_create_files(self):
        self.assertEqual(self.store.read()["settings"], default_settings())
        self.assertFalse(self.directory.exists())

    def test_restart_preserves_only_allowed_settings(self):
        expected = schedule()
        expected["rules"][0]["times"][0] = "08:15"
        self.store.update("schedule", expected)
        self.store.update("theme", "dark")
        self.store.update("fox", {"version": 1, "show": False, "animate": False})
        actual = LocalSettings(self.directory).read()["settings"]
        self.assertEqual(actual["schedule"], expected)
        self.assertEqual(actual["theme"], "dark")
        self.assertEqual(actual["fox"], {"version": 1, "show": False, "animate": False})
        self.assertEqual(set(p.name for p in self.directory.iterdir()), {"settings.json"})
        self.assertEqual(set(actual), {"schemaVersion", "schedule", "theme", "fox"})

    def test_invalid_payload_never_replaces_previous_settings(self):
        self.store.update("theme", "dark")
        before = (self.directory / "settings.json").read_bytes()
        values = []
        for key in ("html", "students", "password", "token", "cookies", "studentUid"):
            bad = schedule()
            bad[key] = "DO_NOT_STORE"
            values.append(bad)
        bad = schedule(); bad["rules"][0]["weekday"] = True; values.append(bad)
        bad = schedule(); bad["rules"][0]["times"] = ["24:00"]; values.append(bad)
        bad = schedule(); bad["rules"][0]["times"] = ["08:05", "08:05"]; values.append(bad)
        bad = schedule(); bad["rules"][1] = deepcopy(bad["rules"][0]); values.append(bad)
        bad = schedule(); bad["rules"][0]["reconciliation"] = "07:00"; values.append(bad)
        bad = schedule(); bad["timezone"] = "../secrets"; values.append(bad)
        for value in values:
            with self.subTest(value=list(value)):
                with self.assertRaises(ValueError): self.store.update("schedule", value)
                self.assertEqual((self.directory / "settings.json").read_bytes(), before)
        for field, value in [("html", "DO_NOT_STORE"), ("theme", "DO_NOT_STORE"), ("fox", {"version":1, "show":True, "animate":True, "password":"DO_NOT_STORE"})]:
            with self.assertRaises(ValueError): self.store.update(field, value)
        self.assertNotIn(b"DO_NOT_STORE", before)

    def test_bad_file_recovers_without_backing_up_arbitrary_content(self):
        self.directory.mkdir()
        path = self.directory / "settings.json"
        for raw in (b"{broken", b"\xff", b"x" * 16001, b'{"password":"DO_NOT_ECHO"}', b"[]"):
            with self.subTest(raw_size=len(raw)):
                path.write_bytes(raw)
                result = self.store.read()
                self.assertEqual(result["settings"], default_settings())
                self.assertTrue(result["notice"])
                self.assertNotIn("DO_NOT_ECHO", result["notice"])
                self.assertEqual(path.read_bytes(), raw)
                self.store.update("theme", "light")
                self.assertEqual(LocalSettings(self.directory).read()["settings"]["theme"], "light")
                self.assertEqual([p.name for p in self.directory.iterdir()], ["settings.json"])

    def test_atomic_replace_failure_keeps_original_and_cleans_temp(self):
        self.store.update("theme", "dark")
        path = self.directory / "settings.json"
        before = path.read_bytes()
        with patch("coletor.local_settings.os.replace", side_effect=OSError("DO_NOT_ECHO")):
            with self.assertRaises(OSError): self.store.update("theme", "light")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual([p.name for p in self.directory.iterdir()], ["settings.json"])

    def test_other_application_files_remain_unchanged(self):
        other = self.root / "Atualizador de Planilhas"
        other.mkdir()
        sentinel = other / "settings.json"
        sentinel.write_text("UNRELATED_APP_SENTINEL", encoding="utf-8")
        self.store.update("schedule", schedule())
        self.store.update("theme", "dark")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "UNRELATED_APP_SENTINEL")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["Atualizador de Planilhas", "ColetorFrequenciaSmecel"])

    def test_profile_directory_is_dedicated_and_not_created(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            self.assertEqual(user_settings_directory(), self.root / "ColetorFrequenciaSmecel")
        self.assertFalse((self.root / "ColetorFrequenciaSmecel").exists())

    def test_bridge_has_only_preview_and_specific_settings_methods(self):
        api = DesktopApi(self.directory)
        self.assertEqual([n for n in dir(api) if not n.startswith("_")],
                         ["get_local_settings", "load_demo", "preview_html", "save_fox", "save_schedule", "save_theme"])
        self.assertFalse(api.load_demo()["validation"]["allowed"])
        api.preview_html("<html>synthetic-invalid</html>", "TESTE-A", 2026)
        self.assertFalse(self.directory.exists())
        self.assertIn("settings", api.save_schedule(schedule()))
        self.assertIn("error", api.save_theme("DO_NOT_STORE"))

    def test_bridge_errors_do_not_echo_paths_or_inputs(self):
        api = DesktopApi(self.directory)
        with patch.object(api._settings, "update", side_effect=OSError("secret/path/DO_NOT_ECHO")):
            result = api.save_theme("dark")
        self.assertNotIn("DO_NOT_ECHO", json.dumps(result))
        self.assertIn("error", result)
        with patch.object(api._settings, "read", side_effect=OSError("secret/path/DO_NOT_ECHO")):
            result = api.get_local_settings()
        self.assertEqual(result["settings"], default_settings())
        self.assertNotIn("DO_NOT_ECHO", json.dumps(result))

if __name__ == "__main__":
    unittest.main()

