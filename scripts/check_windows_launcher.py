"""Native parent EXE/argument/error tests, with disposable synthetic Python code.

The distributed launcher and official Python bytes are copied unchanged. Only the
temporary coletor.portable module is a QA harness; no test flag exists in product.
The native phase additionally runs the bundled desktop/tray with synthetic access
and preferences, through EXE, CMD, Start Menu and Startup shortcut contracts.
"""
import argparse
import ctypes
from ctypes import wintypes
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("launcher_builder", ROOT / "scripts/build_windows_portable.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
spec = importlib.util.spec_from_file_location("launcher_smoke", ROOT / "scripts/check_windows_portable.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


HARNESS = r'''
import ctypes, json, os, sys, time
from pathlib import Path
report = Path(os.environ["COLLECTOR_QA_REPORT"])
data = {"argv": sys.argv[1:], "cwd_matches": Path.cwd() == Path(sys.executable).parent,
        "no_console": not bool(ctypes.windll.kernel32.GetConsoleWindow()), "child": os.getpid(), "parent": os.getppid()}
if os.environ.get("COLLECTOR_QA_NATIVE") == "1":
    sys.path.insert(0, os.environ["COLLECTOR_QA_SCRIPTS"])
    import check_windows_portable as smoke
    from coletor.desktop import run_desktop
    def callback(window):
        try:
            tray = window._coletor_tray
            smoke.wait_js(window, "!!document.querySelector('h1') && !!window.pywebview?.api?.get_desktop_status")
            background = "--background" in sys.argv[1:]
            data["tray_active"] = tray.available() and not tray._disposed
            data["window_visibility"] = bool(window.native.Visible) == (not background)
            data["window_icon"] = window.native.Icon is not None
            data["tray_icon"] = tray._notify.Icon is not None
            data["status"] = "passed" if all(data[k] for k in ("tray_active", "window_visibility", "window_icon", "tray_icon")) else "failed"
        except BaseException:
            data["status"] = "failed"
        finally:
            report.write_text(json.dumps(data), encoding="utf-8")
            smoke.close_window(window)
    run_desktop(callback, Path(os.environ["COLLECTOR_QA_SETTINGS"]),
                access=smoke.synthetic_institutional_access(authorized=False), background="--background" in sys.argv[1:])
else:
    data["status"] = "passed"
    report.write_text(json.dumps(data), encoding="utf-8")
    time.sleep(1.5)  # Parent has time to acquire our exact parent process handle.
    raise SystemExit(int(os.environ.get("COLLECTOR_QA_EXIT", "0")))
'''


def wait_result(path, process, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        if process.poll() not in (None, 0):
            raise RuntimeError("launcher-entrypoint-failed")
        time.sleep(.05)
    raise RuntimeError("launcher-entrypoint-timeout")


def make_shortcut(path, target, args):
    result = builder.powershell(r'''
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($env:COLLECTOR_QA_LINK)
$link.TargetPath = $env:COLLECTOR_QA_TARGET
$link.Arguments = $env:COLLECTOR_QA_ARGS
$link.WorkingDirectory = Split-Path $env:COLLECTOR_QA_TARGET
$link.IconLocation = $env:COLLECTOR_QA_TARGET + ',0'
$link.Save()
''', env=dict(os.environ, COLLECTOR_QA_LINK=str(path), COLLECTOR_QA_TARGET=str(target), COLLECTOR_QA_ARGS=args))
    if result.returncode:
        raise RuntimeError("synthetic-shortcut-creation-failed")


def close_error_popup(pid):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    found = []
    def visit(handle, unused):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        name = ctypes.create_unicode_buffer(100)
        user32.GetClassNameW(handle, name, len(name))
        if owner.value == pid and name.value == "#32770":
            user32.PostMessageW(handle, 0x0010, 0, 0)
            found.append(True)
        return True
    user32.EnumWindows(callback_type(visit), 0)
    return bool(found)


def wait_parent(pid, target):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:  # It may already have exited after native teardown.
        return
    try:
        if kernel.WaitForSingleObject(handle, 0) == 0:
            return
        path = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(path))
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)) or Path(path.value).resolve() != target.resolve():
            raise RuntimeError("launcher-parent-identity-mismatch")
        if kernel.WaitForSingleObject(handle, 30000) != 0:
            raise RuntimeError("launcher-parent-left-running")
    finally:
        kernel.CloseHandle(handle)


def worker(root, output, native):
    if sys.stdin.readline() != "RUN\n":
        return 2
    checks = {}
    runtime = root / "programa"
    target = runtime / builder.LAUNCHER
    arguments = ["space value", "", 'embedded"quote', "trailing slash\\", 'C:\\with space\\', "--background"]
    for mode in ("direct", "cmd", "start-menu", "startup"):
        report = root / (mode + ".json")
        env = dict(os.environ, COLLECTOR_QA_REPORT=str(report), COLLECTOR_QA_NATIVE="1" if native else "0",
                   COLLECTOR_QA_SCRIPTS=str(ROOT / "scripts"), COLLECTOR_QA_SETTINGS=str(root / "settings"))
        if mode == "direct":
            command = [str(target), *([] if native else arguments)]
        elif mode == "cmd":
            command = [str(builder.windows_directory() / "System32/cmd.exe"), "/d", "/c", str(root / "Abrir Coletor.cmd")]
        else:
            link = root / (mode + ".lnk")
            make_shortcut(link, target, "--background" if mode == "startup" else "")
            # Run the .lnk itself through Windows Script Host, not only its target.
            env["COLLECTOR_QA_LINK"] = str(link)
            command = [str(builder.windows_directory() / "System32/WindowsPowerShell/v1.0/powershell.exe"),
                       "-NoProfile", "-NonInteractive", "-Command",
                       "$shell = New-Object -ComObject WScript.Shell; exit $shell.Run(('\"' + $env:COLLECTOR_QA_LINK + '\"'), 1, $true)"]
        process = subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        data = wait_result(report, process)
        # The job owns all descendants, including shell-created shortcut processes.
        process.wait(timeout=100)
        expected = [] if mode in {"cmd", "start-menu"} or (mode == "direct" and native) else ["--background"] if mode == "startup" else arguments
        if (data.get("status") != "passed" or data.get("argv") != expected or not data.get("cwd_matches")
                or not data.get("no_console") or process.returncode):
            raise RuntimeError("launcher-contract-failed-" + mode)
        wait_parent(data["parent"], target)
        checks[mode] = True
        checks[mode + "_launcher_and_python_exited"] = True
        if native:
            checks[mode + "_window_and_tray"] = all(data.get(k) for k in ("tray_active", "window_visibility", "window_icon", "tray_icon"))
    if not native:
        env = dict(os.environ, COLLECTOR_QA_REPORT=str(root / "nonzero.json"), COLLECTOR_QA_EXIT="37")
        result = subprocess.run([str(target), "--background", "private-token-that-must-not-be-logged"], env=env, timeout=30)
        if result.returncode != 37:
            raise RuntimeError("launcher-child-exit-not-propagated")
        checks["nonzero_exit_propagated"] = True
        child = runtime / "pythonw.exe"
        child.rename(runtime / "pythonw.saved")
        try:
            result = subprocess.run([str(target), "--background"], timeout=15)
            if result.returncode != 2:
                raise RuntimeError("launcher-missing-runtime-exit")
            checks["missing_runtime_background_no_popup"] = True
            interactive = subprocess.Popen([str(target)])
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not close_error_popup(interactive.pid):
                time.sleep(.05)
            if interactive.wait(timeout=10) != 2:
                raise RuntimeError("launcher-interactive-error-popup-missing")
            checks["interactive_error_popup"] = True
        finally:
            (runtime / "pythonw.saved").rename(child)
        acl_script = r'''
$ErrorActionPreference = 'Stop'
$file = $env:COLLECTOR_QA_EXECUTABLE
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid, 'ExecuteFile', 'Deny')
$acl = Get-Acl -LiteralPath $file
if ($env:COLLECTOR_QA_RESTORE -eq '1') { [void]$acl.RemoveAccessRuleSpecific($rule) }
else { $acl.AddAccessRule($rule) }
Set-Acl -LiteralPath $file -AclObject $acl
'''
        acl_env = dict(os.environ, COLLECTOR_QA_EXECUTABLE=str(child))
        try:
            if builder.powershell(acl_script, env=acl_env).returncode:
                raise RuntimeError("synthetic-access-denied-setup-failed")
            result = subprocess.run([str(target), "--background"], timeout=15)
            if result.returncode != 5:
                raise RuntimeError("launcher-access-denied-exit")
            checks["access_denied_background_no_popup"] = True
        finally:
            if builder.powershell(acl_script, env=dict(acl_env, COLLECTOR_QA_RESTORE="1")).returncode:
                raise RuntimeError("synthetic-access-denied-cleanup-failed")
        log = Path(os.environ["LOCALAPPDATA"]) / "EcossistemaEscolar/ColetorFrequencia/launcher.log"
        records = log.read_text(encoding="utf-8-sig")
        if ("private-token-that-must-not-be-logged" in records or str(root) in records or
                not all(code in records for code in ("runtime-exit exit=37", "runtime-missing exit=2", "runtime-access-denied exit=5"))):
            raise RuntimeError("launcher-diagnostics-not-sanitized")
        checks["sanitized_local_diagnostics"] = True
        # An invalid executable exercises native Process.Start failure handling.
        child.rename(runtime / "pythonw.saved")
        try:
            child.write_bytes(b"invalid-PE")
            result = subprocess.run([str(target), "--background"], timeout=15)
            if result.returncode not in {193, 216}:  # BAD_EXE_FORMAT or EXE_MACHINE_TYPE_MISMATCH
                raise RuntimeError("launcher-invalid-runtime-exit")
            checks["invalid_runtime_background_no_popup"] = True
        finally:
            child.unlink()
            (runtime / "pythonw.saved").rename(child)
    output.write_text(json.dumps({"status": "passed", "checks": checks}), encoding="utf-8")
    return 0


def run(package_root, output, native=False):
    if sys.platform != "win32":
        raise RuntimeError("windows-required")
    program = package_root / "programa"
    metadata = builder.inspect_binary(program / builder.LAUNCHER)
    manifest = json.loads((package_root / "MANIFEST.json").read_text(encoding="utf-8"))
    expected = manifest["launcher"]
    for key in ("sha256", "file_version", "product_version", "signature_status", "signer_thumbprint"):
        if metadata.get(key) != expected.get(key):
            raise RuntimeError("launcher-inventory-mismatch-" + key)
    with (program / builder.LAUNCHER).open("rb") as file:
        file.seek(0x3c)
        pe = struct.unpack("<I", file.read(4))[0]
        file.seek(pe + 24 + 68)
        if struct.unpack("<H", file.read(2))[0] != 2:
            raise RuntimeError("launcher-is-not-windowed-PE")
    result = {"test": "windows_launcher", "status": "failed", "native_ui": native, "synthetic_data_only": True,
              "real_accounts": False, "real_network": False, "launcher_signature_status": metadata["signature_status"],
              "cleanup_policy": "launcher-and-python-exit; owned-browser-descendants-job-cleanup", "checks": {}}
    with tempfile.TemporaryDirectory(prefix="coletor-launcher-qa-") as temporary:
        root = Path(temporary) / "pacote com espaço"
        root.mkdir()
        runtime = root / "programa"
        if native:
            shutil.copytree(program, runtime)
        else:
            runtime.mkdir()
            for glob in ("pythonw.exe", "*.dll", "*.pyd", "python*.zip", builder.LAUNCHER):
                for file in program.glob(glob):
                    shutil.copyfile(file, runtime / file.name)
            (runtime / "python313._pth").write_text("python313.zip\n.\napp\n", encoding="ascii")
        app = runtime / "app/coletor"
        app.mkdir(parents=True, exist_ok=True)
        if not native:
            (app / "__init__.py").write_text("", encoding="ascii")
        (app / "portable.py").write_text(HARNESS, encoding="utf-8")
        shutil.copyfile(package_root / "Abrir Coletor.cmd", root / "Abrir Coletor.cmd")
        report = root / "worker.json"
        job = smoke.WindowsJob()
        process = None
        try:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", "--package-root", str(root),
                                        "--output", str(report), *(["--native"] if native else [])],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            job.assign(process.pid)
            stdout, stderr = process.communicate(input=b"RUN\n", timeout=450)
            if process.returncode or not report.is_file():
                raise RuntimeError("launcher-worker-failed: " + builder.compiler_diagnostic(stderr.decode("utf-8", "replace"), root))
            result.update(json.loads(report.read_text(encoding="utf-8")))
        finally:
            result["cleanup"] = job.finish(grace=5)
            job.close()
            if process is not None:
                process.wait(timeout=15)
            if not result["cleanup"]["verified"] or result["cleanup"]["remaining_processes"] != 0:
                result["status"] = "failed"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if result["status"] != "passed":
        raise RuntimeError("launcher-smoke-failed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        raise SystemExit(worker(args.package_root, args.output, args.native))
    run(args.package_root.resolve(), args.output.resolve(), args.native)
    print("windows-launcher-smoke-passed")
