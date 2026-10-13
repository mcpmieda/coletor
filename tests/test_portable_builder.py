import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

PATH = Path(__file__).resolve().parents[1] / "scripts/build_windows_portable.py"
spec = importlib.util.spec_from_file_location("portable_builder", PATH)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PortableBuildTests(unittest.TestCase):
    def test_manual_distribution_gate_rejects_missing_consent_isolation_and_cleanup(self):
        native = {"bundled_application", "native_window_visible", "prepared_without_browser", "opening_requires_consent",
                  "separate_edge_started", "reading_requires_consent", "manual_preview_rendered", "transmission_blocked",
                  "cancelled_result_hidden", "session_scope_cleared", "browser_processes_stopped", "window_closed"}
        report = {"status": "passed", "cleanup": {"verified": True, "remaining_processes": 0},
                  "real_network": False, "real_credentials": False, "checks": {key: True for key in native}}
        builder.validate_manual_evidence(report)
        for key in native:
            report["checks"][key] = False
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Manual"):
                builder.validate_manual_evidence(report)
            report["checks"][key] = True
        report["cleanup"]["remaining_processes"] = 1
        with self.assertRaisesRegex(ValueError, "Manual"):
            builder.validate_manual_evidence(report)

    def test_tray_proof_cannot_omit_exit_or_motion_checks(self):
        checks = {"native_window_visible", "native_tray_registered", "native_menu_visible",
                  "same_window_after_repeated_show_hide", "left_click_and_double_click_restore_same_window",
                  "idle_has_no_timer", "saved_preferences_respected", "native_exit_removed_icon_and_timer", "window_closed",
                  "actual_local_reading_state", "reading_animation_bounded", "reduced_motion_stops_native_timer",
                  "disabled_animation_stops_native_timer", "cancel_keeps_actual_native_read_truthful",
                  "discard_blocks_new_reads", "discarded_result_stays_hidden",
                  "error_state_static_and_generic", "hidden_fox_uses_neutral_icon", "visible_ui_healthy", "unregistered_tray_cannot_hide", "hidden_and_minimized_panel_motion_stops"}
        report = {"test":"portable_windows_tray", "status":"passed", "cleanup":{"verified":True,"remaining_processes":0},
                  "only_nonsecret_settings_retained":True, "workers":[{"scenario":s,"status":"passed","cleanup":{"verified":True,"remaining_processes":0},"checks":{k:True for k in checks}} for s in ("quit","close")]}
        builder.validate_tray_evidence(report)
        for name in ("native_exit_removed_icon_and_timer","reduced_motion_stops_native_timer","native_tray_registered"):
            with self.subTest(name=name):
                report["workers"][0]["checks"][name]=False
                with self.assertRaisesRegex(ValueError,"tray"): builder.validate_tray_evidence(report)
                report["workers"][0]["checks"][name]=True
        report["cleanup"]["remaining_processes"]=1
        with self.assertRaisesRegex(ValueError,"tray"): builder.validate_tray_evidence(report)

    def test_runtime_url_and_hash_are_pinned(self):
        self.assertTrue(builder.PYTHON_URL.startswith("https://www.python.org/ftp/python/"))
        self.assertEqual(len(builder.PYTHON_SHA256), 64)
        self.assertIn("3.13.16", builder.PYTHON_URL)

    def test_archive_traversal_is_rejected(self):
        for name in ("../outside", "/absolute", "C:/drive", "folder\\escape"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                with ZipFile(root / "bad.zip", "w") as z:
                    member = ZipInfo("placeholder")
                    member.filename = name  # Preserve hostile backslashes on Windows too.
                    z.writestr(member, "no")
                with self.assertRaises(ValueError):
                    builder.safe_extract(root / "bad.zip", root / "output")

    def test_ordinary_runtime_members_extract(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with ZipFile(root / "ok.zip", "w") as z:
                z.writestr("python313._pth", "python313.zip")
            builder.safe_extract(root / "ok.zip", root / "output")
            self.assertEqual((root / "output/python313._pth").read_text(), "python313.zip")

    def test_package_rejects_missing_or_incomplete_settings_proof(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            basic = root / "basic.json"
            basic.write_text(json.dumps({"status":"passed", "cleanup":{"verified":True}}))
            with self.assertRaisesRegex(ValueError, "local settings"):
                builder.package_zip(root, basic)
            settings = root / "settings.json"
            settings.write_text(json.dumps({"test":"portable_windows_local_settings", "status":"passed", "cleanup":{"verified":True},
                                            "other_application_unchanged":True, "only_nonsecret_settings_retained":True, "workers":[]}))
            with self.assertRaisesRegex(ValueError, "local settings"):
                builder.package_zip(root, basic, settings)

    def test_package_requires_native_smoke_success(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "failed.json").write_text('{"passed":false}')
            with self.assertRaises(ValueError):
                builder.package_zip(root, root / "failed.json")

