"""Assemble a private test bundle from official Python and locked PyPI packages.

Runs only on Windows x64. No installer, registry write, credentials or production
access. The native smoke must pass separately before package_zip is called.
"""
import argparse
import base64
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
def product_version(root=ROOT, build=None):
    """major.minor come from app/coletor/__init__.py; CI's build number becomes the
    third part, so every published build carries a newer version."""
    text = (root / "app/coletor/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"$', text, re.M)
    if not match or any(int(part) > 65535 for part in match[1].split(".")):
        raise ValueError("Product version must be a three-part Windows-compatible version")
    if not build:
        return match[1]
    if not re.fullmatch(r"[1-9]\d{0,4}", build) or int(build) > 65535:
        raise ValueError("Build number must be 1-65535")
    major, minor, _ = match[1].split(".")
    return f"{major}.{minor}.{build}"


PRODUCT_VERSION = product_version(build=os.environ.get("COLETOR_BUILD"))
VERSION = PRODUCT_VERSION + "-teste"
NAME = f"ColetorFrequencia-{VERSION}-windows-x64"
PYTHON_VERSION = "3.13.16"
PYTHON_URL = "https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip"
PYTHON_SHA256 = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297"
DEFAULT_OUTPUT = ROOT / "dist/windows-portable"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_extract(archive, destination):
    """Only ordinary relative files from the hash-verified Python archive."""
    with ZipFile(archive) as z:
        for entry in z.infolist():
            p = PurePosixPath(entry.filename)
            if (p.is_absolute() or ".." in p.parts or "\\" in entry.orig_filename
                    or ":" in entry.filename or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("Unsafe runtime archive path")
            target = destination.joinpath(*p.parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as out:
                    out.write(z.read(entry))


def ui_license_notices(destination):
    """Retain notices for installed npm packages, including build dependencies."""
    notices = []
    for package in sorted((ROOT / "ui/node_modules").rglob("package.json")):
        try:
            meta = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        texts = []
        for f in sorted(package.parent.iterdir()):
            if f.is_file() and re.match(r"^(licen[cs]e|copying|notice)([.\-_]|$)", f.name, re.I):
                texts.append(f.read_text(encoding="utf-8", errors="replace"))
        if texts:
            notices.append(f"{meta.get('name', package.parent.name)} {meta.get('version', '')}\n" + "\n".join(texts))
    (destination / "LICENCAS-UI.txt").write_text("\n\n-----\n\n".join(notices), encoding="utf-8")


LAUNCHER = "ColetorFrequencia.exe"


def windows_directory():
    if sys.platform != "win32":
        raise RuntimeError("Windows compiler inspection requires Windows")
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer))
    if not 0 < size < len(buffer):
        raise RuntimeError("Cannot resolve canonical Windows directory")
    windows = Path(buffer.value).resolve(strict=True)
    if os.environ.get("WINDIR") and Path(os.environ["WINDIR"]).resolve() != windows:
        raise RuntimeError("WINDIR differs from the operating system directory")
    return windows


def powershell(script, *, env=None):
    directory = windows_directory() / "System32/WindowsPowerShell/v1.0"
    executable = directory / "powershell.exe"
    # Do not inherit PowerShell 7 modules or a user-controlled module search path.
    env = dict(os.environ if env is None else env, PSModulePath=str(directory / "Modules"))
    script = "$ProgressPreference = 'SilentlyContinue';\n" + script
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                          env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=90)


def inspect_binary(path):
    """Read signature/PE metadata through the OS, without executing the binary."""
    env = dict(os.environ, COLLECTOR_INSPECT_BINARY=str(path))
    result = powershell(r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$path = $env:COLLECTOR_INSPECT_BINARY
$item = Get-Item -LiteralPath $path
$sig = Get-AuthenticodeSignature -LiteralPath $path
$version = $item.VersionInfo
[ordered]@{
    file_version = $version.FileVersion; product_version = $version.ProductVersion
    company = $version.CompanyName; original_filename = $version.OriginalFilename
    description = $version.FileDescription; signature_status = [string]$sig.Status
    signer = $(if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { $null })
    signer_thumbprint = $(if ($sig.SignerCertificate) { $sig.SignerCertificate.Thumbprint } else { $null })
    timestamped = ($null -ne $sig.TimeStamperCertificate)
} | ConvertTo-Json -Compress
''', env=env)
    if result.returncode:
        raise RuntimeError("Windows binary signature/metadata inspection failed: " + path.name)
    metadata = json.loads(result.stdout.lstrip("\ufeff"))
    metadata["sha256"] = sha256(path)
    return metadata


def trusted_compiler():
    """Accept only the canonical, Microsoft-signed Windows .NET compiler."""
    windows = windows_directory()
    folder = windows / "Microsoft.NET/Framework64/v4.0.30319"
    evidence = []
    # Explicit /nostdlib references below prevent compiler probing other SDKs.
    for name in ("csc.exe", "mscorlib.dll", "System.dll", "System.Windows.Forms.dll"):
        path = folder / name
        if not path.is_file() or path.resolve() != path:
            raise RuntimeError("Required system compiler component missing or redirected: " + name)
        meta = inspect_binary(path)
        if (meta.get("signature_status") != "Valid" or "O=Microsoft Corporation" not in (meta.get("signer") or "")
                or meta.get("company") != "Microsoft Corporation" or not meta.get("file_version")):
            raise RuntimeError("Microsoft compiler component validation failed: " + name)
        if name == "csc.exe" and (meta.get("original_filename") or "").lower() != "csc.exe":
            raise RuntimeError("Unexpected compiler identity")
        evidence.append({"path": path.relative_to(windows).as_posix(), **meta})
    return folder / "csc.exe", evidence


def compiler_diagnostic(value, *private_paths):
    for path in sorted((str(p) for p in (*private_paths, Path.home(), ROOT)), key=len, reverse=True):
        value = re.sub(re.escape(path), "<build>", value, flags=re.I)
    return value[-16000:]


def write_installer_version(output, version=PRODUCT_VERSION):
    # The Inno preprocessor consumes this build output, not a second version literal.
    name = f"ColetorFrequencia-{version}-teste-windows-x64"
    (output / "version.iss").write_text(f'#define AppVersion "{version}"\n'
        f'#define BundleRoot "..\\dist\\windows-portable\\{name}"\n', encoding="ascii")


def build_launcher(runtime, *, version=PRODUCT_VERSION, source=None, icon=None):
    """Compile and optionally sign the parent EXE before its inventory/hashes."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or any(int(p) > 65535 for p in version.split(".")):
        raise ValueError("Invalid launcher product version")
    csc, compiler = trusted_compiler()
    source = source or ROOT / "installer/launcher/ColetorFrequencia.cs"
    icon = icon or ROOT / "app/assets/fox-icons/fox-idle.ico"
    target = runtime / LAUNCHER
    try:
        with tempfile.TemporaryDirectory(prefix="coletor-assembly-") as temporary:
            attributes = Path(temporary) / "Version.cs"
            attributes.write_text('using System.Reflection;\n'
                f'[assembly: AssemblyVersion("{version}.0")]\n'
                f'[assembly: AssemblyFileVersion("{version}.0")]\n'
                f'[assembly: AssemblyInformationalVersion("{version}")]\n', encoding="utf-8")
            command = [str(csc), "-nologo", "-target:winexe", "-platform:x64", "-optimize", "-utf8output", "-codepage:65001", "-noconfig", "-nostdlib+",
                       *["-reference:" + str(csc.parent / name) for name in ("mscorlib.dll", "System.dll", "System.Windows.Forms.dll")],
                       "-win32icon:" + str(icon), "-out:" + str(target), str(attributes), str(source)]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            if result.returncode:
                raise RuntimeError(f"Launcher compiler exited {result.returncode}: " +
                                   compiler_diagnostic(result.stdout + result.stderr, runtime, temporary, source.parent))
        # Existing project signing configuration is optional; never create a key.
        signing = powershell("& $env:COLLECTOR_SIGN_SCRIPT -Path $env:COLLECTOR_SIGN_TARGET; exit $LASTEXITCODE",
                             env=dict(os.environ, COLLECTOR_SIGN_SCRIPT=str(ROOT / "installer/sign-installer.ps1"),
                                      COLLECTOR_SIGN_TARGET=str(target)))
        if signing.returncode:
            raise RuntimeError("Configured launcher code signing failed")
        metadata = inspect_binary(target)
        if metadata.get("signature_status") == "NotSigned":
            metadata["trust"] = "unsigned"
        elif metadata.get("signature_status") in {"Valid", "UnknownError", "NotTrusted"} and metadata.get("signer"):
            metadata["trust"] = "signed-valid" if metadata["signature_status"] == "Valid" else "signed-untrusted"
        else:
            raise RuntimeError("Launcher signature failed verification")
        if metadata.get("file_version") != version + ".0" or metadata.get("product_version") != version:
            raise RuntimeError("Launcher version differs from product version")
        return {"file": "programa/" + LAUNCHER, "version_source": "app/coletor/__init__.py", "compiler": compiler,
                "child_identity": "pythonw.exe; original Python identity and PSF signature, not inherited", **metadata}
    except BaseException:
        if target.is_file():
            target.unlink(missing_ok=True)
        raise


def build(output, source_commit):
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Build requires Windows x64")
    if sys.version_info[:2] != (3, 13):
        raise SystemExit("Build environment must use Python 3.13")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Full source commit required")
    if not (ROOT / "ui/dist/index.html").is_file():
        raise ValueError("Build the UI first")
    bundle = output / NAME
    bundle.mkdir(parents=True, exist_ok=False)
    runtime = bundle / "programa"
    runtime.mkdir()
    archive = output / "python-runtime.zip"
    with urllib.request.urlopen(PYTHON_URL, timeout=60) as response, archive.open("wb") as target:
        shutil.copyfileobj(response, target)
    if sha256(archive) != PYTHON_SHA256:
        raise ValueError("Official Python archive SHA-256 does not match")
    safe_extract(archive, runtime)
    # Preserve signed official Python bytes. The separate parent has its own trust.
    (runtime / "python313._pth").write_text("python313.zip\n.\nLib\\site-packages\napp\nimport site\n", encoding="ascii")
    site = runtime / "Lib/site-packages"
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
        "--no-warn-script-location", "--no-compile", "--require-hashes", "--no-build-isolation", "--target", str(site),
        "--index-url", "https://pypi.org/simple", "-r", str(ROOT / "requirements-windows-portable.txt")], check=True)
    # Only application code and built static UI; no diaries, captures or profiles.
    app = runtime / "app/coletor"
    app.mkdir(parents=True)
    for p in sorted((ROOT / "app/coletor").glob("*.py")):
        shutil.copyfile(p, app / p.name)
    init = app / "__init__.py"
    init.write_text(re.sub(r'^__version__ = ".*"$', f'__version__ = "{PRODUCT_VERSION}"',
                           init.read_text(encoding="utf-8"), count=1, flags=re.M), encoding="utf-8")
    shutil.copyfile(ROOT / "app/coletor/preview-limits.json", app / "preview-limits.json")
    shutil.copytree(ROOT / "app/assets", runtime / "app/assets")
    shutil.copytree(ROOT / "ui/dist", runtime / "ui/dist")
    launcher = build_launcher(runtime)
    shutil.copyfile(ROOT / "docs/PORTABLE_LEIA_ME.txt", bundle / "LEIA-ME.txt")
    (bundle / "Abrir Coletor.cmd").write_bytes(
        b'@echo off\r\nsetlocal\r\nstart "Coletor de Frequencia" "%~dp0programa\\ColetorFrequencia.exe"\r\n')
    (bundle / "Remover acesso deste PC.cmd").write_bytes(
        b'@echo off\r\nsetlocal\r\necho Feche o Coletor antes de continuar.\r\n'
        b'echo Esta acao retira o acesso deste PC; nao apaga a pasta nem configuracoes.\r\n'
        b'choice /C SN /N /M "Continuar (S/N)? "\r\nif errorlevel 2 exit /b 0\r\n'
        b'"%~dp0programa\\python.exe" -B -m coletor --safe-removal\r\n'
        b'set "cleanup_result=%errorlevel%"\r\npause\r\nexit /b %cleanup_result%\r\n')
    ui_license_notices(bundle)
    packages = sorted([{"name": d.metadata["Name"], "version": d.version}
        for d in importlib.metadata.distributions(path=[str(site)])], key=lambda x: x["name"].lower())
    driver_node = subprocess.run([str(site / "playwright/driver/node.exe"), "--version"],
                                 check=True, capture_output=True, text=True).stdout.strip()
    if driver_node != "v24.21.0":
        raise ValueError("Unexpected browser driver Node runtime")
    manifest = {"application": "Coletor de Frequência", "version": VERSION, "product_version": PRODUCT_VERSION, "launcher": launcher,
        "kind": "portable-test-not-installer", "source_commit": source_commit,
        "built_at": datetime.now(timezone.utc).isoformat(), "platform": "windows-x64",
        "python_version": PYTHON_VERSION, "python_url": PYTHON_URL,
        "python_archive_sha256": PYTHON_SHA256, "packages": packages,
        "browser_driver_node_version": driver_node,
        "production_access": "signed-v2-frequency; requires-approved-backend-and-human-activation", "automatic_collection": False,
        "transmission_enabled": False, "frequency_v2_supported": True,
        "real_source_qa": "pending-authorized-operator-validation",
        "credentials_included": False, "tray_enabled": True,
        "native_smoke": "must-pass-before-zip", "files": []}
    for p in sorted(bundle.rglob("*")):
        if p.is_file():
            manifest["files"].append({"path": p.relative_to(bundle).as_posix(), "size": p.stat().st_size, "sha256": sha256(p)})
    (bundle / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_installer_version(output)
    print(json.dumps({"bundle": str(bundle), "files": len(manifest["files"])}))


def validate_tray_evidence(report):
    common = {"native_window_visible", "native_tray_registered", "native_menu_visible",
              "same_window_after_repeated_show_hide", "left_click_and_double_click_restore_same_window",
              "idle_motion_gentle", "window_icon_follows_fox", "fox_icon_shown", "native_exit_removed_icon_and_timer", "window_closed", "visible_ui_healthy", "unregistered_tray_cannot_hide", "hidden_and_minimized_panel_motion_stops"}
    extended = {"menu_header_shows_live_status", "menu_collect_and_pause_reach_collector", "actual_collection_state",
                "collect_disabled_while_collecting", "reading_animation_bounded", "reduced_motion_stops_native_timer",
                "error_state_static_and_generic", "menu_header_flags_error", "menu_notifications_and_logs"}
    close = {"active_collection_close_hides"}
    workers = report.get("workers", [])
    if (report.get("test") != "portable_windows_tray" or report.get("status") != "passed"
            or report.get("cleanup", {}).get("verified") is not True
            or report.get("cleanup", {}).get("remaining_processes") != 0
            or report.get("only_nonsecret_settings_retained") is not True
            or not isinstance(workers, list) or len(workers) != 2
            or {w.get("scenario") for w in workers if isinstance(w, dict)} != {"quit", "close"}):
        raise ValueError("Native tray test must pass before creating a distributable")
    for worker in workers:
        required = common | (extended if worker["scenario"] == "quit" else close)
        if (worker.get("status") != "passed" or worker.get("cleanup", {}).get("verified") is not True
                or worker.get("cleanup", {}).get("remaining_processes") != 0
                or any(worker.get("checks", {}).get(key) is not True for key in required)):
            raise ValueError("Native tray test must pass before creating a distributable")


def validate_manual_evidence(report, browser=False):
    required = ({"external_edge", "no_privileged_bridge", "exact_scope", "password_form_rejected",
                 "credentials_removed", "outside_origin_blocked", "popup_closed", "manual_preview_blocked",
                 "ephemeral_context_closed", "owned_processes_stopped", "get_redirect_destination_uncontacted",
                 "post307_destination_uncontacted", "post308_destination_uncontacted", "authorized_redirect_preserved", "http2_disabled", "proxy_self_test", "webrtc_disabled", 'dpapi_source_session_restored'} if browser else
                {"bundled_application", "native_window_visible", "prepared_without_browser", "opening_requires_consent",
                 "separate_edge_started", "post_open_synthetic_login_navigation", "classes_discovered_without_ct", "selection_persisted_and_revalidated", "no_student_link_opened", "closing_choice_ends_session", "session_scope_cleared", "browser_processes_stopped", "owned_temporaries_removed", "window_closed"})
    if (report.get("status") != "passed" or report.get("cleanup", {}).get("verified") is not True
            or report.get("cleanup", {}).get("remaining_processes") != 0
            or report.get("real_network") is not False or report.get("real_credentials") is not False
            or not all(report.get("checks", {}).get(key) is True for key in required)):
        raise ValueError("Manual session QA must pass before creating a distributable")
    if browser and (type(report.get("denied_destination_contacts")) is not int
                    or report["denied_destination_contacts"] != 0
                    or type(report.get("denied_destination_body_bytes")) is not int
                    or report["denied_destination_body_bytes"] != 0):
        raise ValueError("Denied redirect destinations must never be contacted")


def package_zip(output, evidence, settings_evidence=None, tray_evidence=None, manual_evidence=None, browser_evidence=None, device_evidence=None, frequency_evidence=None):
    bundle = output / NAME
    report = json.loads(evidence.read_text(encoding="utf-8"))
    if report.get("status") != "passed" or report.get("cleanup", {}).get("verified") is not True:
        raise ValueError("Native Windows smoke must pass before creating a distributable")
    if settings_evidence is None:
        raise ValueError("Native local settings test must pass before creating a distributable")
    settings_report = json.loads(settings_evidence.read_text(encoding="utf-8"))
    workers = settings_report.get("workers", [])
    if (settings_report.get("test") != "portable_windows_local_settings" or settings_report.get("status") != "passed"
            or settings_report.get("cleanup", {}).get("verified") is not True
            or settings_report.get("other_application_unchanged") is not True
            or settings_report.get("only_nonsecret_settings_retained") is not True
            or not isinstance(workers, list) or len(workers) != 4
            or {w.get("scenario") for w in workers if isinstance(w, dict)} != {"save", "reopen", "restored", "recovered"}
            or any(w.get("status") != "passed" or w.get("cleanup", {}).get("verified") is not True
                   or w.get("checks", {}).get("window_closed") is not True
                   or w.get("checks", {}).get("native_window_visible") is not True for w in workers)):
        raise ValueError("Native local settings test must pass before creating a distributable")
    if tray_evidence is None:
        raise ValueError("Native tray test must pass before creating a distributable")
    validate_tray_evidence(json.loads(tray_evidence.read_text(encoding="utf-8")))
    if manual_evidence is None or browser_evidence is None:
        raise ValueError("Manual session QA must pass before creating a distributable")
    validate_manual_evidence(json.loads(manual_evidence.read_text(encoding="utf-8")))
    validate_manual_evidence(json.loads(browser_evidence.read_text(encoding="utf-8")), browser=True)
    if device_evidence is None:
        raise ValueError("Anonymous native device proof QA must pass before packaging")
    device = json.loads(device_evidence.read_text(encoding="utf-8"))
    required = {"native-cng-pairing-verified-by-backend", "native-cng-access-verified-by-backend", "native-cng-revoke-verified-by-backend",
                "native-cng-frequency-verified-by-backend", "native-cng-frequency-altered-payload-rejected"}
    if (device.get("passed") is not True or device.get("synthetic_backend") is not True
            or device.get("real_network") is not False or device.get("real_accounts") is not False
            or device.get("named_keys_created") != 0 or device.get("anonymous_keys_created") != 1
            or device.get("anonymous_keys_released") != 1 or not required.issubset(device.get("checks", []))):
        raise ValueError("Anonymous native device proof QA must pass before packaging")
    if frequency_evidence is None: raise ValueError('Native operational frequency proof must pass before packaging')
    frequency = json.loads(frequency_evidence.read_text(encoding='utf-8'))
    if (frequency.get('test') != 'portable_windows_frequency_v2' or frequency.get('status') != 'passed'
            or frequency.get('bundled_runtime') is not True or frequency.get('synthetic_data_only') is not True
            or frequency.get('real_network') is not False or frequency.get('real_accounts') is not False
            or frequency.get('failures') != 0 or frequency.get('errors') != 0 or frequency.get('skips') != 0
            or not isinstance(frequency.get('tests'), int) or frequency['tests'] < 22
            or any(frequency.get('checks', {}).get(k) is not True for k in
                   ('native_dpapi', 'runtime_receipts_pause_fencing_cancellation', 'instance_lock', 'no_named_keys'))):
        raise ValueError('Native operational frequency proof must pass before packaging')
    manifest_path = bundle / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["native_smoke"] = "passed-in-private-windows-ci"
    manifest["local_settings_smoke"] = "passed-in-private-windows-ci"
    manifest["tray_smoke"] = "passed-in-private-windows-ci"
    manifest["manual_session_smoke"] = "passed-synthetic-native-and-external-edge"
    manifest["device_proof_smoke"] = "anonymous-cng-verified-by-backend-fixture"
    manifest['frequency_v2_smoke'] = 'bundled-native-dpapi-and-operational-regressions'
    manifest["institutional_activation"] = "pending-backend-configuration-and-authorized-tenant-validation"
    manifest["persistent_key_qa"] = "not-proven; requires-explicit-human-activation"
    manifest["tray_scope"] = "same-window-show-hide-exit; operational-activity; close-hides-while-collecting; portable-no-autostart"
    manifest["local_settings"] = "nonsecret-preferences; dpapi-session-and-queue-only-with-native-consent; shared-server-agenda"
    for item in manifest["files"]:
        p = bundle / item["path"]
        if p.stat().st_size != item["size"] or sha256(p) != item["sha256"]:
            raise ValueError("Packaged file changed after build")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    path = output / f"{NAME}.zip"
    with ZipFile(path, "w", ZIP_DEFLATED, compresslevel=9) as z:
        # Package only the pre-test inventory. Never sweep up a profile or log.
        for name in [item["path"] for item in manifest["files"]] + ["MANIFEST.json"]:
            z.write(bundle / name, NAME + "/" + name)
    (output / (path.name + ".sha256")).write_text(f"{sha256(path)}  {path.name}\n", encoding="ascii")
    print(json.dumps({"file": str(path), "size": path.stat().st_size, "sha256": sha256(path)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-commit")
    parser.add_argument("--package", type=Path, help="Successful native smoke JSON")
    parser.add_argument("--settings-evidence", type=Path, help="Successful native settings close/reopen/recovery JSON")
    parser.add_argument("--tray-evidence", type=Path, help="Successful native notification-area flows JSON")
    parser.add_argument("--manual-evidence", type=Path, help="Successful native manual-session flow JSON")
    parser.add_argument("--browser-evidence", type=Path, help="Successful isolated Edge synthetic QA JSON")
    parser.add_argument("--device-evidence", type=Path, help="Successful anonymous CNG/backend interoperability QA JSON")
    parser.add_argument('--frequency-evidence', type=Path, help='Successful bundled native frequency/DPAPI evidence')
    args = parser.parse_args()
    if args.package:
        package_zip(args.output, args.package, args.settings_evidence, args.tray_evidence, args.manual_evidence, args.browser_evidence, args.device_evidence, args.frequency_evidence)
    else:
        build(args.output, args.source_commit or "")

