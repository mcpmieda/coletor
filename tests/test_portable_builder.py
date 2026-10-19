import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

PATH = Path(__file__).resolve().parents[1] / "scripts/build_windows_portable.py"
spec = importlib.util.spec_from_file_location("portable_builder", PATH)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PortableBuildTests(unittest.TestCase):
    def test_version_is_derived_from_product_and_future_version_reaches_inno(self):
        self.assertEqual(builder.VERSION, builder.product_version() + "-teste")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app/coletor").mkdir(parents=True)
            (root / "app/coletor/__init__.py").write_text('__version__ = "8.12.3"\n', encoding="utf-8")
            self.assertEqual(builder.product_version(root), "8.12.3")
            builder.write_installer_version(root, builder.product_version(root))
            include = (root / "version.iss").read_text()
            self.assertIn('#define AppVersion "8.12.3"', include)
            self.assertIn("ColetorFrequencia-8.12.3-teste-windows-x64", include)
            self.assertNotIn(builder.PRODUCT_VERSION, include)
        inno = (builder.ROOT / "installer/Coletor.iss").read_text(encoding="utf-8")
        self.assertIn('version.iss"', inno)
        self.assertNotIn('#define AppVersion "', inno)

    def test_compiler_requires_canonical_signed_microsoft_components(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            folder = root / "Microsoft.NET/Framework64/v4.0.30319"
            folder.mkdir(parents=True)
            for name in ("csc.exe", "mscorlib.dll", "System.dll", "System.Windows.Forms.dll"):
                (folder / name).touch()
            valid = {"signature_status": "Valid", "signer": "CN=Microsoft Windows, O=Microsoft Corporation, C=US",
                     "company": "Microsoft Corporation", "file_version": "4.8.1", "original_filename": "csc.exe"}
            with patch.object(builder, "windows_directory", return_value=root), patch.object(builder, "inspect_binary", return_value=valid):
                compiler, evidence = builder.trusted_compiler()
                self.assertEqual(compiler, folder / "csc.exe")
                self.assertEqual(len(evidence), 4)
                self.assertTrue(all("Microsoft.NET/Framework64" in record["path"] for record in evidence))
            for key, value in (("signature_status", "HashMismatch"), ("signer", "CN=Different Company"), ("company", "Untrusted"), ("original_filename", "alternate.exe")):
                with self.subTest(key=key), patch.object(builder, "windows_directory", return_value=root), patch.object(builder, "inspect_binary", return_value={**valid, key: value}):
                    with self.assertRaisesRegex(RuntimeError, "compiler"):
                        builder.trusted_compiler()
            (folder / "csc.exe").unlink()
            with patch.object(builder, "windows_directory", return_value=root), self.assertRaisesRegex(RuntimeError, "missing"):
                builder.trusted_compiler()

    def test_compiler_failure_shows_cs_code_and_removes_partial_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / builder.LAUNCHER
            target.write_bytes(b"partial")
            failure = subprocess.CompletedProcess([], 1, str(root) + "/Source.cs(1,1): error CS1002: ; expected", "")
            with patch.object(builder, "trusted_compiler", return_value=(root / "csc.exe", [])), patch.object(builder.subprocess, "run", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, "CS1002") as caught:
                    builder.build_launcher(root)
                self.assertNotIn(str(root), str(caught.exception))
            self.assertFalse(target.exists())

    @unittest.skipUnless(sys.platform == "win32", "real Windows compiler required")
    def test_native_compiler_future_version_and_useful_invalid_input_errors(self):
        with tempfile.TemporaryDirectory(prefix="coletor-compiler-test-") as temporary:
            root = Path(temporary)
            with patch.dict(os.environ, {key: "" for key in ("WINDOWS_SIGNING_BUNDLE_BASE64", "WINDOWS_SIGNING_PFX_BASE64", "WINDOWS_SIGNING_PFX_PASSWORD")}):
                metadata = builder.build_launcher(root, version="8.12.3")
                self.assertEqual(metadata["file_version"], "8.12.3.0")
                self.assertEqual(metadata["product_version"], "8.12.3")
                self.assertEqual(metadata["description"], "Coletor de Frequência")
                self.assertEqual(metadata["trust"], "unsigned")
                bad_source = root / "invalid.cs"
                bad_source.write_text("this is not C#", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "CS[0-9]+"):
                    builder.build_launcher(root, source=bad_source)
                self.assertFalse((root / builder.LAUNCHER).exists())
                bad_icon = root / "invalid.ico"
                bad_icon.write_text("not an icon", encoding="ascii")
                with self.assertRaisesRegex(RuntimeError, "CS[0-9]+"):
                    builder.build_launcher(root, icon=bad_icon)
                self.assertFalse((root / builder.LAUNCHER).exists())
                (root / builder.LAUNCHER).mkdir()
                with self.assertRaisesRegex(RuntimeError, "CS[0-9]+"):
                    builder.build_launcher(root)
            with patch.dict(os.environ, {"WINDIR": str(root)}), self.assertRaisesRegex(RuntimeError, "WINDIR differs"):
                builder.windows_directory()

    def test_manual_distribution_gate_rejects_missing_consent_isolation_and_cleanup(self):
        native = {"bundled_application", "native_window_visible", "prepared_without_browser", "opening_requires_consent",
                  "separate_edge_started", "post_open_synthetic_login_navigation", "classes_discovered_without_ct", "selection_persisted_and_revalidated", "no_student_link_opened",
                  "closing_choice_ends_session", "session_scope_cleared", "browser_processes_stopped", "owned_temporaries_removed", "window_closed"}
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
                  "idle_motion_gentle", "window_icon_follows_fox", "fox_icon_shown", "native_exit_removed_icon_and_timer", "window_closed",
                  "menu_header_shows_live_status", "menu_collect_and_pause_reach_collector", "actual_collection_state",
                  "collect_disabled_while_collecting", "reading_animation_bounded", "reduced_motion_stops_native_timer",
                  "error_state_static_and_generic", "menu_header_flags_error", "menu_notifications_and_logs", "visible_ui_healthy", "unregistered_tray_cannot_hide", "hidden_and_minimized_panel_motion_stops",
                  "active_collection_close_hides"}
        report = {"test":"portable_windows_tray", "status":"passed", "cleanup":{"verified":True,"remaining_processes":0},
                  "only_nonsecret_settings_retained":True, "workers":[{"scenario":s,"status":"passed","cleanup":{"verified":True,"remaining_processes":0},"checks":{k:True for k in checks}} for s in ("quit","close")]}
        builder.validate_tray_evidence(report)
        for index, name in ((0,"native_exit_removed_icon_and_timer"),(0,"reduced_motion_stops_native_timer"),(0,"native_tray_registered"),(1,"active_collection_close_hides")):
            with self.subTest(name=name):
                report["workers"][index]["checks"][name]=False
                with self.assertRaisesRegex(ValueError,"tray"): builder.validate_tray_evidence(report)
                report["workers"][index]["checks"][name]=True
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

