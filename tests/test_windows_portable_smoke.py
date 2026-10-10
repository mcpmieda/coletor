"""Portable-window smoke contracts; these mocks do NOT count as Windows QA."""
from contextlib import nullcontext
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_windows_portable.py"
SPEC = importlib.util.spec_from_file_location("windows_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class Registry:
    HKEY_LOCAL_MACHINE = "machine"
    HKEY_CURRENT_USER = "user"
    KEY_WOW64_32KEY = 0x200
    KEY_WOW64_64KEY = 0x100
    KEY_READ = 1
    REG_SZ = 1

    def __init__(self, versions):
        self.versions = iter(versions)
        self.read_keys = []

    def OpenKey(self, hive, key, reserved, permissions):
        self.read_keys.append((hive, key, permissions))
        return nullcontext(object())

    def QueryValueEx(self, handle, name):
        value = next(self.versions)
        if isinstance(value, BaseException):
            raise value
        return value, self.REG_SZ


class SmokeContractsTests(unittest.TestCase):
    def test_version_probe_accepts_only_numeric_nonzero_versions(self):
        for value in (None, "", "0.0.0.0", "123-beta", "secret/path", 123, "12\n"):
            with self.subTest(value=value):
                self.assertIsNone(smoke.numeric_version(value))
        self.assertEqual(smoke.numeric_version("130.0.1234.56"), "130.0.1234.56")

    def test_runtime_probe_reads_official_keys_without_installation(self):
        registry = Registry([FileNotFoundError(), "131.0.1.2", "130.0.0.3", "0.0.0.0"])
        actual = smoke.probe_webview2(registry)
        self.assertTrue(actual["installed"])
        self.assertEqual(actual["version"], "131.0.1.2")
        self.assertFalse(actual["installation_attempted"])
        self.assertEqual(len(registry.read_keys), 4)
        self.assertTrue(all(smoke.WEBVIEW2_GUID in key[1] for key in registry.read_keys))

    def test_runtime_probe_missing_fails_closed(self):
        actual = smoke.probe_webview2(Registry([FileNotFoundError(), "", "0.0.0.0", PermissionError()]))
        self.assertFalse(actual["installed"])
        self.assertIsNone(actual["version"])

    def test_package_contract_requires_bundled_interpreter_ui_and_app(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(smoke.SmokeFailure, "portable_package_incomplete"):
                smoke.validate_package(root)
            for relative in ("python.exe", "pythonw.exe", "app/coletor/desktop.py", "ui/dist/index.html"):
                file = root / "programa" / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.touch()
            self.assertEqual(smoke.validate_package(root), root / "programa")

    def test_python_argument_resolves_package_root(self):
        args = smoke.parse_args(["--python", "build/MyApp/programa/python.exe", "--output-dir", "artifacts"])
        self.assertEqual(args.package_root, Path("build/MyApp").resolve())
        self.assertTrue(args.output_dir.is_absolute())

    def test_timeout_and_worker_output_are_required(self):
        for arguments in (["--package-root", ".", "--timeout", "0"], ["--package-root", ".", "--worker"],
                          ["--python", "pythonw.exe"], ["--package-root", ".", "--timeout", "nan"]):
            with self.subTest(arguments=arguments), patch("sys.stderr", new=io.StringIO()):
                with self.assertRaises(SystemExit):
                    smoke.parse_args(arguments)

    def test_non_windows_is_failure_with_json_and_no_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            args = smoke.parse_args(["--package-root", directory, "--output-dir", directory])
            with patch.object(smoke.sys, "platform", "linux"), patch.object(smoke.subprocess, "Popen") as spawn, patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(smoke.run_orchestrator(args), 1)
            spawn.assert_not_called()
            evidence = json.loads((Path(directory) / "windows-portable-smoke.json").read_text())
            self.assertEqual(evidence["failure"], "windows_runner_required")
            self.assertTrue(evidence["window_test"])
            self.assertFalse(evidence["headless_substitute"])
            self.assertNotIn(directory, json.dumps(evidence))

    def test_worker_does_not_start_until_contained(self):
        with patch("sys.stdin", new=io.StringIO("")), patch.object(smoke, "validate_package") as validate:
            self.assertEqual(smoke.run_worker(object()), 2)
            validate.assert_not_called()

    def test_js_requires_real_button_bridge_and_three_students(self):
        self.assertIn("realLoadDemo.apply", smoke.INSTALL_OBSERVER_JS)
        self.assertIn("result?.validation?.allowed === false", smoke.INSTALL_OBSERVER_JS)
        self.assertIn("apiFetches === 0", smoke.rendered_js(1))
        self.assertIn("state?.calls === 2", smoke.rendered_js(2))
        self.assertEqual(len(smoke.EXPECTED_NAMES), 3)
        self.assertIn("window_closed", smoke.REQUIRED_CHECKS)

    def test_wait_js_stops_with_timeout(self):
        window = MagicMock()
        window.evaluate_js.return_value = False
        with patch.object(smoke.time, "monotonic", side_effect=[0, 0.5, 2]), patch.object(smoke.time, "sleep"):
            with self.assertRaisesRegex(smoke.SmokeFailure, "javascript_condition_timeout"):
                smoke.wait_js(window, "test", timeout=1)

    def test_callback_error_closes_window_and_omits_exception_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "worker.json"
            window = MagicMock()
            window.evaluate_js.side_effect = ValueError("sensitive/local/path/DO_NOT_ECHO")
            evidence = {"checks": {}, "_worker_output": str(output)}
            smoke.exercise_window(window, evidence, Path(directory) / "capture.png")
            window.destroy.assert_called_once()
            actual = output.read_text()
            self.assertNotIn("DO_NOT_ECHO", actual)
            self.assertNotIn(directory, actual)
            self.assertEqual(json.loads(actual)["failure"], "window_check_failed")


class OrchestrationTests(unittest.TestCase):
    def run_mocked(self, worker_pass=True, timeout=False, omit_check=None, cleanup=True):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        args = smoke.parse_args(["--package-root", str(root), "--output-dir", str(root / "evidence")])
        process, job = MagicMock(), MagicMock()
        process.returncode = None
        process.poll.side_effect = lambda: process.returncode
        job.finish.return_value = {"verified": cleanup, "remaining_processes": 0 if cleanup else 1}
        holder = {}

        def spawn(command, **kwargs):
            holder["command"] = command
            holder["kwargs"] = kwargs
            return process

        def communicate(**kwargs):
            holder["input"] = kwargs["input"]
            output = Path(holder["command"][holder["command"].index("--worker-output") + 1])
            checks = {name: True for name in smoke.REQUIRED_CHECKS}
            if omit_check:
                checks.pop(omit_check)
            smoke.write_json(output, {"status": "passed" if worker_pass else "failed", "checks": checks})
            if timeout:
                raise subprocess.TimeoutExpired("private-path-not-for-evidence", 150)
            process.returncode = 0 if worker_pass else 1
            return None, None

        def wait(**kwargs):
            if process.returncode is None:
                process.returncode = 1
            return process.returncode

        process.communicate.side_effect = communicate
        process.wait.side_effect = wait
        with patch.object(smoke.sys, "platform", "win32"), patch.object(smoke, "validate_package", return_value=root / "programa"), \
                patch.object(smoke, "probe_webview2", return_value={"installed": True}), patch.object(smoke, "WindowsJob", return_value=job), \
                patch.object(smoke.subprocess, "Popen", side_effect=spawn), patch("sys.stdout", new=io.StringIO()):
            result = smoke.run_orchestrator(args)
        return result, json.loads((args.output_dir / "windows-portable-smoke.json").read_text()), process, job, holder

    def test_success_uses_bundled_python_and_verifies_cleanup(self):
        result, evidence, process, job, holder = self.run_mocked()
        self.assertEqual(result, 0)
        self.assertEqual(evidence["status"], "passed")
        self.assertTrue(evidence["cleanup"]["verified"])
        self.assertTrue(holder["command"][0].endswith("programa/python.exe"))
        self.assertEqual(holder["command"][1], "-I")
        self.assertEqual(holder["input"], b"RUN\n")
        job.assign.assert_called_once_with(process.pid)
        job.close.assert_called_once()
        self.assertEqual(holder["kwargs"]["stdout"], subprocess.DEVNULL)

    def test_timeout_fails_even_if_worker_wrote_passed(self):
        result, evidence, process, job, _ = self.run_mocked(timeout=True)
        self.assertEqual(result, 1)
        self.assertEqual(evidence["failure"], "native_window_timeout")
        job.finish.assert_called_once_with(grace=0)
        job.close.assert_called_once()

    def test_incomplete_window_proof_cannot_pass(self):
        result, evidence, *_ = self.run_mocked(omit_check="edgechromium_control")
        self.assertEqual(result, 1)
        self.assertEqual(evidence["status"], "failed")

    def test_missing_cleanup_proof_cannot_pass(self):
        result, evidence, *_ = self.run_mocked(cleanup=False)
        self.assertEqual(result, 1)
        self.assertFalse(evidence["cleanup"]["verified"])

    def test_worker_failure_cannot_pass(self):
        result, evidence, *_ = self.run_mocked(worker_pass=False)
        self.assertEqual(result, 1)
        self.assertEqual(evidence["worker_exit_code"], 1)


if __name__ == "__main__":
    unittest.main()
