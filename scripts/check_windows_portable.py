#!/usr/bin/env python3
"""Exercise the *real* portable Windows window; never substitutes a browser test.

Run on a Windows desktop-capable CI runner with WebView2 already present::

    python scripts/check_windows_portable.py --package-root dist/Coletor \
        --output-dir artifacts/windows-smoke --timeout 150

The orchestrator launches programa/python.exe, from an unrelated directory, then
calls the bundled desktop.run_desktop(callback). The callback uses pywebview's
public evaluate_js/destroy/native APIs and clicks the real demo button. An OS job
contains the worker and WebView2 descendants, including if GUI calls deadlock.
No runtime installation, login, source diary, database or collection is involved.
Evidence contains only fixed labels, synthetic counts, versions and booleans.

API references:
https://pywebview.flowrl.com/api/
https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution
https://learn.microsoft.com/windows/win32/procthread/job-objects
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

SCHEMA = 1
WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
EXPECTED_NAMES = [f"Aluno sintético {number:03}" for number in range(1, 4)]
LABELS = ["Conferir frequência", "Não envia dados", "Prévia da turma",
          "Alunos no diário", "Este exemplo usa alunos fictícios.",
          "Nenhum dado foi enviado", "• não confirma presença", "Envio desativado"]
REQUIRED_CHECKS = ["bundled_interpreter", "bundled_application", "bundled_pywebview",
                   "native_window_visible", "edgechromium_control", "loopback_ui",
                   "dom_and_bridge_ready", "real_demo_button_clicked", "bridge_demo_verified",
                   "demo_rendered", "three_synthetic_options", "student_filter_works",
                   "clear_preview_works", "repeat_demo_works", "window_closed"]


class SmokeFailure(RuntimeError):
    """Only fixed, non-sensitive error codes may be stored in evidence."""


def fail(code: str) -> None:
    raise SmokeFailure(code)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def numeric_version(value: object) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+){1,3}", value) and any(int(n) for n in value.split(".")):
        return value
    return None


def probe_webview2(registry=None) -> dict:
    """Read the official Evergreen Runtime registry keys, never install it."""
    if registry is None:
        import winreg as registry
    candidates = []
    key = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_GUID}"
    # Explicit registry views also cover a 32-bit orchestrator on 64-bit Windows.
    for hive_name in ("HKEY_LOCAL_MACHINE", "HKEY_CURRENT_USER"):
        for view in (registry.KEY_WOW64_32KEY, registry.KEY_WOW64_64KEY):
            try:
                with registry.OpenKey(getattr(registry, hive_name), key, 0, registry.KEY_READ | view) as handle:
                    value, value_type = registry.QueryValueEx(handle, "pv")
                parsed = numeric_version(value) if value_type == registry.REG_SZ else None
                if parsed:
                    candidates.append(parsed)
            except OSError:
                continue
    return {"installed": bool(candidates), "version": max(candidates, key=lambda item: tuple(map(int, item.split(".")))) if candidates else None,
            "method": "evergreen_registry_read_only", "installation_attempted": False}


def validate_package(root: Path) -> Path:
    program = root / "programa"
    for relative in ("python.exe", "pythonw.exe", "app/coletor/desktop.py", "ui/dist/index.html"):
        if not (program / relative).is_file():
            fail("portable_package_incomplete")
    return program


class WindowsJob:
    """Kill only this smoke's process tree, not unrelated Python/Edge processes."""

    def __init__(self):
        from ctypes import wintypes as w

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in ("TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")] + [
                (name, w.DWORD) for name in ("TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")]

        self._accounting_type = Accounting
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self._kernel, name)
            function.argtypes, function.restype = arguments, result
        self._handle = self._kernel.CreateJobObjectW(None, None)
        if not self._handle:
            fail("process_job_create_failed")
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._kernel.SetInformationJobObject(self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            fail("process_job_limits_failed")

    def assign(self, pid: int) -> None:
        process = self._kernel.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
        if not process:
            fail("process_job_open_failed")
        try:
            if not self._kernel.AssignProcessToJobObject(self._handle, process):
                fail("process_job_assign_failed")
        finally:
            self._kernel.CloseHandle(process)

    def active_count(self) -> int:
        info = self._accounting_type()
        if not self._kernel.QueryInformationJobObject(self._handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
            fail("process_job_query_failed")
        return int(info.ActiveProcesses)

    def finish(self, grace: float = 5.0) -> dict:
        deadline = time.monotonic() + grace
        while self.active_count() and time.monotonic() < deadline:
            time.sleep(0.1)
        forced = self.active_count() != 0
        if forced and not self._kernel.TerminateJobObject(self._handle, 1):
            fail("process_job_terminate_failed")
        deadline = time.monotonic() + 10
        while self.active_count() and time.monotonic() < deadline:
            time.sleep(0.1)
        remaining = self.active_count()
        return {"method": "windows_job_object", "forced_descendant_cleanup": forced,
                "remaining_processes": remaining, "verified": remaining == 0}

    def close(self) -> None:
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


def wait_js(window, script: str, timeout: float = 35) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = window.evaluate_js(script)
        if result:
            return result
        time.sleep(0.1)
    fail("javascript_condition_timeout")


def click_button(window, label: str) -> None:
    script = """(() => {
      const button = [...document.querySelectorAll('button')].find(node => node.textContent.trim() === %s);
      if (!button || button.disabled) return false;
      button.click(); return true;
    })()""" % json.dumps(label)
    if not window.evaluate_js(script):
        fail("expected_button_unavailable")


INSTALL_OBSERVER_JS = """(() => {
  const api = window.pywebview?.api;
  if (!api || typeof api.load_demo !== 'function' || window.__portableSmoke) return false;
  const state = window.__portableSmoke = {calls: 0, completed: 0, valid: false, apiFetches: 0};
  const realLoadDemo = api.load_demo;
  api.load_demo = function(...args) {
    state.calls += 1;
    return realLoadDemo.apply(this, args).then(result => {
      state.completed += 1;
      const names = (result?.snapshot?.students || []).map(student => student.display_name).sort();
      state.valid = result?.mode === 'demo' && result?.validation?.allowed === false &&
        JSON.stringify(names) === JSON.stringify(%s);
      return result;
    });
  };
  const realFetch = window.fetch;
  window.fetch = function(input, ...args) {
    const target = typeof input === 'string' ? input : input?.url || '';
    if (target.includes('/api/')) state.apiFetches += 1;
    return realFetch.call(this, input, ...args);
  };
  return true;
})()""" % json.dumps(EXPECTED_NAMES)


def rendered_js(expected_calls: int) -> str:
    return """(() => {
      const state = window.__portableSmoke;
      const summary = [...document.querySelectorAll('.summary-grid > div')];
      const values = Object.fromEntries(summary.map(node => [node.querySelector('span')?.textContent.trim(), node.querySelector('strong')?.textContent.trim()]));
      const text = document.body.innerText;
      return state?.calls === %d && state.completed === %d && state.valid && state.apiFetches === 0 &&
        values['Alunos no diário'] === '3' && values['Dados enviados'] === '0' &&
        document.querySelectorAll('tbody tr').length === 24 &&
        %s.every(label => text.includes(label));
    })()""" % (expected_calls, expected_calls, json.dumps(LABELS))


def native_info(window) -> tuple[dict, int]:
    """Inspect the public native control on its own WinForms UI thread."""
    from System import Action
    info = {"visible": False, "edgechromium": False, "runtime_version": None}
    handle = []

    def inspect():
        form = window.native
        info["visible"] = bool(form.Visible) and not bool(form.IsDisposed)
        handle.append(int(form.Handle.ToInt64()))
        pending = list(form.Controls)
        while pending:
            control = pending.pop()
            if str(control.GetType().FullName) == "Microsoft.Web.WebView2.WinForms.WebView2":
                info["edgechromium"] = True
                info["runtime_version"] = numeric_version(str(control.CoreWebView2.Environment.BrowserVersionString))
            pending.extend(list(control.Controls))

    window.native.Invoke(Action(inspect))
    return info, handle[0]


def capture_window(hwnd: int, destination: Path) -> dict:
    """Capture only the real app window; no page re-render or whole-desktop grab.

    GPU-backed PrintWindow can be unsupported on a headless CI desktop. A capture
    is supplementary, never a replacement for the mandatory native/bridge checks.
    """
    from ctypes import wintypes as w
    from System.Drawing import Bitmap, Graphics
    from System.Drawing.Imaging import ImageFormat
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user32.GetWindowRect.restype = w.BOOL
    user32.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
    user32.PrintWindow.restype = w.BOOL
    rectangle = w.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
        return {"status": "unavailable", "reason": "window_rectangle_unavailable"}
    width, height = rectangle.right - rectangle.left, rectangle.bottom - rectangle.top
    if not (1 <= width <= 8192 and 1 <= height <= 8192):
        return {"status": "unavailable", "reason": "window_dimensions_invalid"}
    bitmap = Bitmap(width, height)
    graphics = Graphics.FromImage(bitmap)
    try:
        context = graphics.GetHdc()
        try:
            captured = user32.PrintWindow(hwnd, int(context.ToInt64()), 2)  # PW_RENDERFULLCONTENT
        finally:
            graphics.ReleaseHdc(context)
        if not captured:
            return {"status": "unavailable", "reason": "printwindow_unsupported"}
        # Reject uniform/black browser areas rather than presenting them as proof.
        colors = {int(bitmap.GetPixel(x, y).ToArgb()) for x in range(width // 3, width - 20, max(1, width // 20))
                  for y in range(height // 4, height - 20, max(1, height // 20))}
        if len(colors) < 5:
            return {"status": "unavailable", "reason": "capture_has_insufficient_content"}
        bitmap.Save(str(destination), ImageFormat.Png)
        return {"status": "captured", "file": destination.name, "method": "win32_printwindow",
                "width": width, "height": height}
    finally:
        graphics.Dispose()
        bitmap.Dispose()


def exercise_window(window, evidence: dict, screenshot: Path) -> None:
    checks = evidence["checks"]
    try:
        evidence["stage"] = "dom_and_bridge"
        wait_js(window, "document.readyState === 'complete' && !!document.querySelector('h1') && typeof window.pywebview?.api?.load_demo === 'function'")
        checks["dom_and_bridge_ready"] = True
        info, handle = native_info(window)
        checks["native_window_visible"] = info["visible"]
        checks["edgechromium_control"] = info["edgechromium"]
        evidence["webview2_runtime_version"] = info["runtime_version"]
        if not info["visible"] or not info["edgechromium"]:
            fail("real_edgechromium_window_required")
        location = urlparse(window.get_current_url() or "")
        checks["loopback_ui"] = location.scheme == "http" and location.hostname in ("127.0.0.1", "localhost", "::1")
        if not checks["loopback_ui"]:
            fail("trusted_local_ui_required")
        if not window.evaluate_js(INSTALL_OBSERVER_JS):
            fail("bridge_observer_failed")
        evidence["stage"] = "demo_button"
        click_button(window, "Usar dados de exemplo")
        checks["real_demo_button_clicked"] = True
        wait_js(window, rendered_js(1))
        checks["bridge_demo_verified"] = checks["demo_rendered"] = True
        evidence["synthetic_student_count"] = 3
        evidence["labels_verified"] = list(LABELS)

        evidence["stage"] = "student_filter"
        if not window.evaluate_js("""(() => {
          const button = document.querySelector('.filters button');
          if (!button) return false;
          button.click(); return true;
        })()"""):
            fail("student_filter_unavailable")
        wait_js(window, """(() => {
          const names = [...document.querySelectorAll('[role=option]')].map(node => node.textContent.trim());
          return %s.every(name => names.includes(name));
        })()""" % json.dumps(EXPECTED_NAMES))
        checks["three_synthetic_options"] = True
        if not window.evaluate_js("""(() => {
          const option = [...document.querySelectorAll('[role=option]')].find(node => node.textContent.trim() === 'Aluno sintético 002');
          if (!option) return false;
          option.click(); return true;
        })()"""):
            fail("student_option_unavailable")
        wait_js(window, "document.querySelectorAll('tbody tr').length === 24 && [...document.querySelectorAll('tbody tr')].every(row => row.textContent.includes('Aluno sintético 002'))")
        checks["student_filter_works"] = True

        evidence["stage"] = "clear_and_repeat"
        click_button(window, "Fechar diário")
        wait_js(window, "!document.querySelector('.preview-panel') && !!document.querySelector('.empty-state')")
        checks["clear_preview_works"] = True
        click_button(window, "Usar dados de exemplo")
        wait_js(window, rendered_js(2))
        checks["repeat_demo_works"] = True
        evidence["bridge_demo_calls"] = 2
        evidence["http_api_calls"] = 0
        evidence["stage"] = "screenshot"
        try:
            evidence["screenshot"] = capture_window(handle, screenshot)
        except Exception as error:
            evidence["screenshot"] = {"status": "unavailable", "reason": "capture_failed", "error_type": type(error).__name__}
        evidence["status"] = "passed"
    except Exception as error:
        evidence["status"] = "failed"
        evidence["failure"] = str(error) if isinstance(error, SmokeFailure) else "window_check_failed"
        evidence["error_type"] = type(error).__name__
    finally:
        write_json(Path(evidence.pop("_worker_output")), evidence)
        window.destroy()


def run_worker(args) -> int:
    # Gate prevents all GUI/browser descendants until the parent assigns its job.
    if sys.stdin.readline() != "RUN\n":
        return 2
    evidence = {"status": "failed", "stage": "worker_start", "checks": {},
                "_worker_output": str(args.worker_output)}
    try:
        program = validate_package(args.package_root)
        evidence["checks"]["bundled_interpreter"] = Path(sys.executable).resolve() == (program / "python.exe").resolve()
        if not evidence["checks"]["bundled_interpreter"]:
            fail("bundled_interpreter_required")
        import coletor.desktop as desktop
        import webview
        evidence["checks"]["bundled_application"] = Path(desktop.__file__).resolve().is_relative_to(program.resolve())
        evidence["checks"]["bundled_pywebview"] = Path(webview.__file__).resolve().is_relative_to(program.resolve())
        if not evidence["checks"]["bundled_application"] or not evidence["checks"]["bundled_pywebview"]:
            fail("package_import_escaped")
        evidence["python_version"] = ".".join(map(str, sys.version_info[:3]))
        evidence["pywebview_version"] = version("pywebview")
        if evidence["pywebview_version"] != "6.1":
            fail("unexpected_pywebview_version")
        evidence["stage"] = "launch_native_window"
        write_json(args.worker_output, {key: value for key, value in evidence.items() if not key.startswith("_")})
        desktop.run_desktop(callback=lambda window: exercise_window(window, evidence, args.output_dir / "windows-portable.png"))
        evidence["checks"]["window_closed"] = True
        evidence["stage"] = "window_closed"
        if evidence["status"] != "passed" or not all(evidence["checks"].get(key) is True for key in REQUIRED_CHECKS):
            fail("required_window_check_failed")
        return_code = 0
    except BaseException as error:
        evidence["status"] = "failed"
        evidence.setdefault("failure", str(error) if isinstance(error, SmokeFailure) else "worker_failed")
        evidence["error_type"] = type(error).__name__
        return_code = 1
    evidence.pop("_worker_output", None)
    write_json(args.worker_output, evidence)
    return return_code


def run_orchestrator(args) -> int:
    started = time.monotonic()
    evidence = {"schema_version": SCHEMA, "status": "failed", "test": "portable_windows_edgechromium_window",
                "started_at": datetime.now(timezone.utc).isoformat(), "stage": "preflight",
                "synthetic_data_only": True, "window_test": True, "headless_substitute": False,
                "timeout_seconds": args.timeout}
    process = job = None
    args.output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = args.output_dir / "windows-portable-smoke.json"
    try:
        if sys.platform != "win32":
            fail("windows_runner_required")
        program = validate_package(args.package_root)
        evidence["webview2_prerequisite"] = probe_webview2()
        if not evidence["webview2_prerequisite"]["installed"]:
            fail("webview2_prerequisite_missing_no_install_attempted")
        with tempfile.TemporaryDirectory(prefix="coletor-window-smoke-") as temporary:
            worker_output = Path(temporary) / "worker-evidence.json"
            command = [str(program / "python.exe"), "-I", str(Path(__file__).resolve()),
                       "--worker", "--package-root", str(args.package_root), "--output-dir", str(args.output_dir),
                       "--worker-output", str(worker_output)]
            job = WindowsJob()
            evidence["stage"] = "spawn_bundled_runtime"
            process = subprocess.Popen(command, cwd=temporary, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, close_fds=True)
            job.assign(process.pid)
            evidence["stage"] = "native_window_test"
            try:
                process.communicate(input=b"RUN\n", timeout=args.timeout)
            except subprocess.TimeoutExpired:
                evidence["failure"] = "native_window_timeout"
            finally:
                evidence["cleanup"] = job.finish(grace=0 if process.poll() is None else 5)
                process.wait(timeout=10)
                evidence["worker_exit_code"] = process.returncode
                if worker_output.is_file():
                    evidence["worker"] = json.loads(worker_output.read_text(encoding="utf-8"))
            worker = evidence.get("worker", {})
            passed = process.returncode == 0 and worker.get("status") == "passed" and all(
                worker.get("checks", {}).get(key) is True for key in REQUIRED_CHECKS)
            if "failure" not in evidence and passed and evidence["cleanup"]["verified"]:
                evidence["status"] = "passed"
                evidence["stage"] = "complete"
            else:
                evidence.setdefault("failure", "native_window_smoke_failed")
    except BaseException as error:
        evidence["failure"] = str(error) if isinstance(error, SmokeFailure) else "orchestrator_failed"
        evidence["error_type"] = type(error).__name__
    finally:
        # A failed assignment leaves a worker at the stdin gate, with no GUI.
        if job is not None:
            try:
                if "cleanup" not in evidence:
                    evidence["cleanup"] = job.finish(grace=0)
            except Exception:
                evidence["cleanup"] = {"verified": False, "method": "windows_job_object"}
            job.close()
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        evidence["elapsed_seconds"] = round(time.monotonic() - started, 2)
        write_json(evidence_path, evidence)
    print(json.dumps({"status": evidence["status"], "evidence": evidence_path.name,
                      "failure": evidence.get("failure")}, ensure_ascii=False))
    return 0 if evidence["status"] == "passed" else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    package = parser.add_mutually_exclusive_group(required=True)
    package.add_argument("--package-root", type=Path)
    package.add_argument("--python", type=Path, dest="python_executable", help="Bundled programa/python.exe to test")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/windows-smoke"))
    parser.add_argument("--timeout", type=float, default=150)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 10 <= args.timeout <= 600:
        parser.error("--timeout must be between 10 and 600 seconds")
    if args.worker and args.worker_output is None:
        parser.error("internal worker requires --worker-output")
    if args.python_executable is not None:
        if args.python_executable.name.lower() != "python.exe":
            parser.error("--python must name the bundled python.exe")
        args.package_root = args.python_executable.resolve().parent.parent
    args.package_root = args.package_root.resolve()
    args.output_dir = args.output_dir.resolve()
    return args


if __name__ == "__main__":
    options = parse_args()
    raise SystemExit(run_worker(options) if options.worker else run_orchestrator(options))
