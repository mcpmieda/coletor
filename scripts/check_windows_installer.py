"""Native Windows installer gate, only a disposable synthetic per-user install.

No account, device key, Smecel login or production endpoint is accessed. The
private installer can be published only when all native browser/security gates
and this real install/uninstall test have succeeded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from xml.etree import ElementTree

LOGON_TASK = r"\EcossistemaEscolar\ColetorFrequencia"
QUIT_EVENT = r"Local\EcossistemaEscolar.ColetorFrequencia.Encerrar"  # app/coletor/instance_lock.py
INSTALL_FLAGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/NOICONS"]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def installed_processes(folder):
    """PIDs of processes started from the installed folder (launcher, pythonw, workers)."""
    script = ("$f = $env:COLETOR_QA_FOLDER.TrimEnd('\\') + '\\'; Get-CimInstance Win32_Process | "
              "Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($f, 'OrdinalIgnoreCase') } | "
              "ForEach-Object { $_.ProcessId }")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                            text=True, timeout=60, env={**os.environ, "COLETOR_QA_FOLDER": str(folder)})
    if result.returncode:
        raise RuntimeError("process-listing-failed")
    return {int(x) for x in result.stdout.split()}


def quit_event_ready():
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenEventW(0x00100000, False, QUIT_EVENT)  # SYNCHRONIZE: open only, never signal.
    if handle: kernel.CloseHandle(handle)
    return bool(handle)


def wait_until(condition, seconds, code):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition(): return
        time.sleep(1)
    raise RuntimeError(code)


def upgrade(installer, installed, log, report, name):
    started = time.monotonic()
    result = subprocess.run([str(installer), *INSTALL_FLAGS, "/DIR=" + str(installed), "/LOG=" + str(log)],
                            capture_output=True, timeout=600, check=False)
    report["upgrade_seconds"][name] = round(time.monotonic() - started, 1)
    if result.returncode != 0:
        raise RuntimeError(f"upgrade-over-running-{name}-exit-{result.returncode}")
    return log.read_text(encoding="utf-8", errors="replace")


def check_upgrade_over_running_app(installer, installed, root, report):
    """Schools get updates while the Coletor runs beside the clock (20/10/2026: exit 5)."""
    report["upgrade_seconds"] = {}
    programa = installed / "programa"
    if installed_processes(installed) or quit_event_ready():
        raise RuntimeError("unexpected-collector-before-upgrade")
    # 1. A Coletor up to 0.4.245 has no quit event and ignores WM_CLOSE: stopped after a short wait.
    legacy = subprocess.Popen([str(programa / "python.exe"), "-B", "-c", "import time; time.sleep(900)"],
                              cwd=programa)
    try:
        wait_until(lambda: legacy.pid in installed_processes(installed), 30, "legacy-process-not-started")
        text = upgrade(installer, installed, root / "upgrade-legacy.log", report, "legacy")
        legacy.wait(timeout=30)
        if "quit event answered: 0" not in text:
            raise RuntimeError("legacy-collector-not-stopped")
    finally:
        if legacy.poll() is None: legacy.kill()
    # The installer reopens what it closed, beside the clock (--background).
    wait_until(quit_event_ready, 120, "collector-not-reopened-after-legacy-upgrade")
    report["checks"]["upgrade_stops_legacy_collector_and_reopens"] = True
    # 2. The real current Coletor, with its tray: asked to quit, it exits by itself.
    before = installed_processes(installed)
    if not before:
        raise RuntimeError("reopened-collector-not-running")
    text = upgrade(installer, installed, root / "upgrade-running.log", report, "running")
    if "quit event answered: 1" not in text or "did not quit in time" in text:
        raise RuntimeError("running-collector-not-closed-cooperatively")
    if before & installed_processes(installed):
        raise RuntimeError("old-collector-process-survived-upgrade")
    wait_until(quit_event_ready, 120, "collector-not-reopened-after-upgrade")
    report["checks"]["upgrade_over_running_app_exits_0_and_reopens"] = True


def run(installer, expected_sha, output):
    if sys.platform != "win32":
        raise RuntimeError("windows-required")
    if not installer.is_file() or installer.stat().st_size < 1_000_000:
        raise RuntimeError("installer-missing-or-incomplete")
    if len(expected_sha) != 40 or any(x not in "0123456789abcdef" for x in expected_sha):
        raise RuntimeError("invalid-head-sha")
    with tempfile.TemporaryDirectory(prefix="collector-installer-qa-") as parent:
        root = Path(parent)
        installed = root / "installed"
        unrelated = root / "unrelated"
        unrelated.mkdir()
        sentinel = unrelated / "do-not-touch.txt"
        sentinel.write_text("synthetic-sentinel", encoding="utf-8")
        report = {"status": "failed", "checks": {}, "real_accounts": False, "real_network": False}
        uninstaller = installed / "unins000.exe"
        try:
            command = [str(installer), *INSTALL_FLAGS, "/DIR=" + str(installed)]
            result = subprocess.run(command, capture_output=True, timeout=150, check=False)
            if result.returncode != 0:
                raise RuntimeError("installer-failed")
            report["checks"]["installed_without_admin"] = True
            manifest_path = installed / "MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("source_commit") != expected_sha or manifest.get("credentials_included") is not False:
                raise RuntimeError("installer-source-mismatch")
            files = manifest["files"]
            if len(files) < 100:
                raise RuntimeError("installer-file-inventory-incomplete")
            for item in files:
                path = installed / item["path"]
                if not path.is_file() or path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
                    raise RuntimeError("installer-file-hash-mismatch")
            report["checks"]["source_commit_and_full_inventory"] = True
            from check_windows_launcher import builder
            launcher = installed / "programa/ColetorFrequencia.exe"
            metadata = builder.inspect_binary(launcher)
            for key in ("sha256", "file_version", "product_version", "signature_status", "signer_thumbprint"):
                if metadata.get(key) != manifest.get("launcher", {}).get(key):
                    raise RuntimeError("installed-launcher-signature-or-version-mismatch")
            if metadata["product_version"] != manifest.get("product_version"):
                raise RuntimeError("installed-product-version-mismatch")
            report["launcher_signature_status"] = metadata["signature_status"]
            report["launcher_trust"] = manifest["launcher"]["trust"]
            report["checks"]["installed_launcher_identity_and_signature"] = True
            python = installed / "programa" / "python.exe"
            if not (installed / "programa" / "pythonw.exe").is_file() or not uninstaller.is_file():
                raise RuntimeError("native-launcher-or-uninstaller-missing")
            help_run = subprocess.run([str(python), "-B", "-m", "coletor", "--help"],
                                      cwd=installed / "programa", capture_output=True, timeout=30)
            if help_run.returncode != 0 or b"--safe-removal" not in help_run.stdout:
                raise RuntimeError("installed-runtime-unavailable")
            report["checks"]["installed_runtime_and_uninstaller"] = True
            startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/Coletor de Frequência.lnk"
            if startup.exists():
                raise RuntimeError("legacy-startup-shortcut-left")
            query = subprocess.run(["schtasks", "/Query", "/TN", LOGON_TASK, "/XML"], capture_output=True, timeout=30)
            if query.returncode:
                raise RuntimeError("logon-task-missing")
            # schtasks prints in the console code page but declares UTF-16; parse the text.
            text = query.stdout.decode("oem", errors="replace")
            task = ElementTree.fromstring(text[text.index("<Task"):])
            ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
            if (Path(task.findtext("t:Actions/t:Exec/t:Command", "", ns)).resolve() != launcher.resolve()
                    or task.findtext("t:Actions/t:Exec/t:Arguments", "", ns) != "--background"
                    or Path(task.findtext("t:Actions/t:Exec/t:WorkingDirectory", "", ns)).resolve() != launcher.parent.resolve()
                    or task.find("t:Triggers/t:LogonTrigger", ns) is None
                    or task.findtext("t:Principals/t:Principal/t:RunLevel", "LeastPrivilege", ns) != "LeastPrivilege"):
                raise RuntimeError("installed-logon-task-contract-mismatch")
            report["checks"]["startup_targets_native_launcher_in_background"] = True
            report["checks"]["opens_at_windows_sign_in_by_default"] = True
            check_upgrade_over_running_app(installer, installed, root, report)
            # The uninstaller closes the reopened Coletor before removing its files.
            uninstall = subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                                       capture_output=True, timeout=150)
            if uninstall.returncode != 0:
                raise RuntimeError("uninstall-failed")
            if (installed / "programa" / "python.exe").exists():
                raise RuntimeError("uninstall-left-program")
            if installed_processes(installed):
                raise RuntimeError("uninstall-left-collector-running")
            if subprocess.run(["schtasks", "/Query", "/TN", LOGON_TASK], capture_output=True, timeout=30).returncode == 0:
                raise RuntimeError("uninstall-left-logon-task")
            if sentinel.read_text(encoding="utf-8") != "synthetic-sentinel":
                raise RuntimeError("uninstall-affected-other-data")
            report["checks"]["uninstall_preserves_unrelated_data"] = True
            report["status"] = "passed"
        finally:
            if installed.exists():
                for pid in installed_processes(installed):
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=30)
            if uninstaller.exists():
                subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                               capture_output=True, timeout=60, check=False)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.installer.resolve(), args.commit, args.output.resolve())
    if report["status"] != "passed":
        raise SystemExit("installer-native-qa-failed")
    print("installer-native-qa-passed", flush=True)


if __name__ == "__main__":
    main()
