"""Automatic update from this repository's GitHub Releases (owner request 15/11/2026).

Only an installed Coletor (Inno Setup uninstaller beside programa/) with a CI build number updates
itself. It reads a small manifest of the latest Release, downloads that version's installer from
the fixed Release URL, checks its size, SHA-256, PE header and the school's signature, and runs it
silently only when no collection or report is running or due. The installer asks this app to quit (it finishes a run in
flight first), replaces the files and reopens it beside the clock. Only github.com and GitHub's
release-asset hosts are contacted, over HTTPS; no token, account or student data is involved.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import quote, urljoin, urlsplit

from .leftovers import remove_leftovers

REPOSITORY = 'mcpmieda/coletor'
MANIFEST_NAME = 'atualizacao.json'
MANIFEST_URL = f'https://github.com/{REPOSITORY}/releases/latest/download/{MANIFEST_NAME}'
ALLOWED_HOSTS = frozenset({'github.com', 'api.github.com', 'release-assets.githubusercontent.com',
                           'objects.githubusercontent.com'})
# .github/workflows/publish-installer.yml writes Releases with this identity. A Release made or changed
# by anyone else (a person, another installed GitHub App) is never installed (owner request 15/11/2026).
# A workflow pushed on another branch could use the same identity: the signature settles that (SIGNERS).
PUBLISHER = 'github-actions[bot]'
RELEASE_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/tags/v{{version}}'
RELEASE_LIMIT = 256 * 1024
MANIFEST_LIMIT = 4096
SETUP_MINIMUM = 1_000_000
SETUP_LIMIT = 300 * 1024 * 1024
FIRST_CHECK_SECONDS = 120
CHECK_EVERY_SECONDS = 6 * 3600
SAFE_RETRY_SECONDS = 60
TIMEOUT_SECONDS = 60
BATTERY_MINIMUM = 40
DISK_FACTOR = 4
VERSION = re.compile(r'(\d{1,5})\.(\d{1,5})\.(\d{1,5})\Z')
HEX_HASH = re.compile(r'[0-9a-f]{64}\Z')
SETUP_ARGUMENTS = ('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCANCEL', '/SP-')
# Same names as installer/Coletor.iss: the resumed installer reopens the Coletor even if none runs.
RESUME_ARGUMENT = '/REABRIR=1'
RUN_ONCE_KEY = r'Software\Microsoft\Windows\CurrentVersion\RunOnce'
RESUME_VALUE = '!ColetorAtualizacao'
INSTALLER_MUTEX = 'EcossistemaEscolar.ColetorFrequencia.Instalador'
SYNCHRONIZE = 0x00100000
INSTALL_LOG = 'instalacao.log'
ATTEMPTS_FILE = 'tentativas.json'
STATE_FILE = 'estado.json'
MAX_ATTEMPTS = 3
ATTEMPT_SPACING_SECONDS = 24 * 3600


class UpdateError(Exception):
    pass


def parse_version(text):
    match = VERSION.fullmatch(text) if isinstance(text, str) else None
    if not match: raise UpdateError('bad-version')
    return tuple(int(part) for part in match.groups())


def setup_name(version):
    # Release assets turn spaces into dots, so the published name has none (scripts/publish_windows_installer.py).
    return f'COLETOR-v{version}.exe'


def setup_url(version):
    return f'https://github.com/{REPOSITORY}/releases/download/v{version}/{quote(setup_name(version))}'


def installed_folder(root):
    """The installation folder (holding unins000.exe) when this copy was installed, else None."""
    folder = Path(root).parent
    return folder if (folder / 'unins000.exe').is_file() else None


def read_manifest(data):
    try: value = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError): raise UpdateError('bad-manifest') from None
    if not isinstance(value, dict) or set(value) != {'versao', 'arquivo', 'sha256', 'tamanho'}:
        raise UpdateError('bad-manifest')
    parse_version(value['versao'])
    if (value['arquivo'] != setup_name(value['versao']) or not isinstance(value['sha256'], str)
            or HEX_HASH.fullmatch(value['sha256']) is None or type(value['tamanho']) is not int
            or not SETUP_MINIMUM <= value['tamanho'] <= SETUP_LIMIT):
        raise UpdateError('bad-manifest')
    return value


def check_publisher(data, manifest):
    """The Release of this version was made, and its two files uploaded, by the publishing workflow."""
    try: release = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError): raise UpdateError('bad-release') from None
    if not isinstance(release, dict) or release.get('tag_name') != f"v{manifest['versao']}" or release.get('draft') is not False:
        raise UpdateError('bad-release')
    if not isinstance(release.get('author'), dict) or release['author'].get('login') != PUBLISHER:
        raise UpdateError('untrusted-release')
    assets = release.get('assets')
    if not isinstance(assets, list): raise UpdateError('bad-release')
    found = {a.get('name'): a for a in assets if isinstance(a, dict)}
    for name in (manifest['arquivo'], MANIFEST_NAME):
        asset = found.get(name)
        if asset is None or asset.get('state') != 'uploaded': raise UpdateError('bad-release')
        if not isinstance(asset.get('uploader'), dict) or asset['uploader'].get('login') != PUBLISHER:
            raise UpdateError('untrusted-release')
    if found[manifest['arquivo']].get('size') != manifest['tamanho']: raise UpdateError('bad-release')


def _connect(host):
    return http.client.HTTPSConnection(host, timeout=TIMEOUT_SECONDS)


def open_download(url, connect=_connect, redirects=4):
    """GET over HTTPS following redirects only between the allowed GitHub hosts.

    Returns (connection, response); the caller reads the body and closes the connection."""
    for _ in range(redirects + 1):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in ALLOWED_HOSTS or parts.port not in {None, 443}:
            raise UpdateError('host-not-allowed')
        connection = connect(parts.hostname)
        try:
            path = parts.path + (f'?{parts.query}' if parts.query else '')
            connection.request('GET', path, headers={'User-Agent': 'Coletor-atualizacao', 'Accept': '*/*'})
            response = connection.getresponse()
        except (OSError, http.client.HTTPException):
            connection.close()
            raise UpdateError('network') from None
        if response.status in {301, 302, 303, 307, 308}:
            location = response.getheader('Location')
            connection.close()
            if not location: raise UpdateError('bad-redirect')
            url = urljoin(url, location)
            continue
        if response.status != 200:
            connection.close()
            raise UpdateError('not-found' if response.status == 404 else 'unavailable')
        return connection, response
    raise UpdateError('too-many-redirects')


def fetch_small(url, limit=MANIFEST_LIMIT, connect=_connect):
    connection, response = open_download(url, connect)
    try:
        data = response.read(limit + 1)
    except (OSError, http.client.HTTPException):
        raise UpdateError('network') from None
    finally:
        connection.close()
    if len(data) > limit: raise UpdateError('too-large')
    return data


def download_setup(manifest, folder, connect=_connect):
    """Download into folder and return the verified installer path; partial files never remain."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / manifest['arquivo']
    if target.is_file() and _verified(target, manifest): return target
    partial = folder / (manifest['arquivo'] + '.part')
    connection, response = open_download(setup_url(manifest['versao']), connect)
    digest, size = hashlib.sha256(), 0
    try:
        with partial.open('wb') as out:
            while True:
                block = response.read(1024 * 1024)
                if not block: break
                size += len(block)
                if size > manifest['tamanho']: raise UpdateError('size-mismatch')
                digest.update(block)
                out.write(block)
    except (OSError, http.client.HTTPException):
        partial.unlink(missing_ok=True)
        raise UpdateError('network') from None
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    finally:
        connection.close()
    if size != manifest['tamanho'] or digest.hexdigest() != manifest['sha256'] or not _is_pe(partial):
        partial.unlink(missing_ok=True)
        raise UpdateError('checksum-mismatch')
    os.replace(partial, target)
    return target


def _verified(path, manifest):
    if path.stat().st_size != manifest['tamanho'] or not _is_pe(path): return False
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest() == manifest['sha256']


def _is_pe(path):
    with path.open('rb') as file:
        header = file.read(64)
        if len(header) != 64 or header[:2] != b'MZ': return False
        offset = int.from_bytes(header[0x3C:0x40], 'little')
        if not 64 <= offset <= 65536: return False
        file.seek(offset)
        return file.read(4) == b'PE\x00\x00'


# The school's code-signing certificate (installer/new-signing-certificate.ps1): SHA-256 of the
# certificate itself. Its key exists only as a secret of the GitHub environment "assinatura", which
# only workflows of the main branch may use. More than one entry while a certificate is replaced.
SIGNERS = frozenset({'929ee6187af8e05d028893cb57d34400c7ec5762c3146763fafb6321dce4ceb0'})
WINTRUST_VERIFY = (0x00AAC56B, 0xCD44, 0x11D0, (0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))
# Intact and trusted, or intact with a root Windows does not know: the certificate is self-signed.
INTACT_SIGNATURE = frozenset({0, 0x800B0109})


def signer(path):
    """SHA-256 (hex) of the certificate whose Authenticode signature this file carries intact, else None.

    Windows itself checks the signature against the file (WinVerifyTrust, no dialog, no network);
    a file with no signature or changed after signing gets another verdict and is refused."""
    if os.name != 'nt': return None
    import ctypes
    from ctypes import wintypes

    class Guid(ctypes.Structure):
        _fields_ = [('a', wintypes.DWORD), ('b', wintypes.WORD), ('c', wintypes.WORD), ('d', ctypes.c_ubyte * 8)]

    class FileInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('path', wintypes.LPCWSTR), ('file', wintypes.HANDLE),
                    ('subject', ctypes.c_void_p)]

    class TrustData(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('policy', ctypes.c_void_p), ('sip', ctypes.c_void_p),
                    ('ui', wintypes.DWORD), ('revocation', wintypes.DWORD), ('choice', wintypes.DWORD),
                    ('file', ctypes.POINTER(FileInfo)), ('action', wintypes.DWORD), ('state', wintypes.HANDLE),
                    ('url', wintypes.LPCWSTR), ('flags', wintypes.DWORD), ('context', wintypes.DWORD),
                    ('settings', ctypes.c_void_p)]

    class Signer(ctypes.Structure):  # CRYPT_PROVIDER_SGNR, up to the chain.
        _fields_ = [('size', wintypes.DWORD), ('verified', wintypes.FILETIME), ('count', wintypes.DWORD),
                    ('chain', ctypes.c_void_p)]

    class ChainCertificate(ctypes.Structure):  # CRYPT_PROVIDER_CERT, up to the certificate.
        _fields_ = [('size', wintypes.DWORD), ('certificate', ctypes.c_void_p)]

    class Certificate(ctypes.Structure):  # CERT_CONTEXT, up to the encoded certificate.
        _fields_ = [('encoding', wintypes.DWORD), ('encoded', ctypes.POINTER(ctypes.c_ubyte)), ('length', wintypes.DWORD)]

    trust = ctypes.WinDLL('wintrust.dll')
    trust.WinVerifyTrust.argtypes = [wintypes.HANDLE, ctypes.POINTER(Guid), ctypes.POINTER(TrustData)]
    trust.WinVerifyTrust.restype = wintypes.LONG
    trust.WTHelperProvDataFromStateData.argtypes = [wintypes.HANDLE]
    trust.WTHelperProvDataFromStateData.restype = ctypes.c_void_p
    trust.WTHelperGetProvSignerFromChain.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    trust.WTHelperGetProvSignerFromChain.restype = ctypes.POINTER(Signer)
    a, b, c, d = WINTRUST_VERIFY
    action = Guid(a, b, c, (ctypes.c_ubyte * 8)(*d))
    file = FileInfo(ctypes.sizeof(FileInfo), str(path), None, None)
    # No dialog (2), no revocation lookup (0 and 0x10), a file (1), cached URLs only (0x1000): nothing leaves this computer.
    data = TrustData(ctypes.sizeof(TrustData), None, None, 2, 0, 1, ctypes.pointer(file), 1, None, None, 0x1010, 0, None)
    no_window = wintypes.HANDLE(-1)
    verdict = trust.WinVerifyTrust(no_window, ctypes.byref(action), ctypes.byref(data)) & 0xFFFFFFFF
    try:
        if verdict not in INTACT_SIGNATURE: return None
        provider = trust.WTHelperProvDataFromStateData(data.state)
        found = trust.WTHelperGetProvSignerFromChain(provider, 0, False, 0) if provider else None
        if not found or not found.contents.count or not found.contents.chain: return None
        leaf = ctypes.cast(found.contents.chain, ctypes.POINTER(ChainCertificate)).contents.certificate
        if not leaf: return None
        certificate = ctypes.cast(leaf, ctypes.POINTER(Certificate)).contents
        return hashlib.sha256(ctypes.string_at(certificate.encoded, certificate.length)).hexdigest()
    finally:
        data.action = 2  # Close the verification state.
        trust.WinVerifyTrust(no_window, ctypes.byref(action), ctypes.byref(data))


def power_ok():
    """Not on a battery below BATTERY_MINIMUM %: a notebook must not die halfway through."""
    if os.name != 'nt': return True
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [('ACLineStatus', ctypes.c_ubyte), ('BatteryFlag', ctypes.c_ubyte),
                    ('BatteryLifePercent', ctypes.c_ubyte), ('SystemStatusFlag', ctypes.c_ubyte),
                    ('BatteryLifeTime', ctypes.c_ulong), ('BatteryFullLifeTime', ctypes.c_ulong)]
    status = Status()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)): return True
    on_battery = status.ACLineStatus == 0
    percent = status.BatteryLifePercent  # 255 = unknown
    return not on_battery or (percent != 255 and percent >= BATTERY_MINIMUM)


def space_ok(folder, size):
    """Room for the download plus the installed copy it replaces (DISK_FACTOR times the installer)."""
    import shutil
    probe = folder if folder.exists() else folder.parent
    try: return shutil.disk_usage(probe).free >= size * DISK_FACTOR
    except OSError: return False


def downloaded_version(path):
    match = re.fullmatch(r'COLETOR-v(\d{1,5}\.\d{1,5}\.\d{1,5})\.exe(\.part)?', path.name)
    return parse_version(match.group(1)) if match else None


def remove_other_setups(folder, keep=None, *, up_to=None):
    """Earlier downloads are not kept: all but keep, or (offline, at start) those up to up_to."""
    if not folder.is_dir(): return
    for path in folder.iterdir():
        if not path.is_file() or path.name == keep or path.suffix not in {'.exe', '.part'}: continue
        if up_to is not None and (downloaded_version(path) or (0, 0, 0)) > up_to: continue
        path.unlink(missing_ok=True)


def setup_arguments(log):
    return [*SETUP_ARGUMENTS, f'/LOG={log}']


def resume_command(path, log):
    return subprocess.list2cmdline([str(path), *setup_arguments(log), RESUME_ARGUMENT])


def schedule_resume(path, log):
    """If Windows turns off mid-install, the next sign-in runs the same installer again.

    The '!' keeps the RunOnce value until that run ends. The installer deletes it when it ends
    (installer/Coletor.iss, ResumeValue); while it exists the launcher does not open the Coletor at
    sign-in, so it never starts from a half-replaced folder (installer/launcher/ColetorFrequencia.cs)."""
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_ONCE_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, RESUME_VALUE, 0, winreg.REG_SZ, resume_command(path, log))


def cancel_resume():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_ONCE_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RESUME_VALUE)
    except OSError:
        pass


def installer_running():
    """The installer holds SetupMutex (installer/Coletor.iss) while it runs."""
    if os.name != 'nt': return False
    import ctypes
    handle = ctypes.windll.kernel32.OpenMutexW(SYNCHRONIZE, False, INSTALLER_MUTEX)
    if not handle: return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def clear_stale_resume():
    """Opened while no installer runs: a resume entry left behind (RunOnce disabled by policy, or
    a resumed run that never came) must not keep the sign-in start from opening the Coletor."""
    if os.name == 'nt' and not installer_running(): cancel_resume()


def launch_setup(path):
    """Start the installer on its own: it outlives this app, which it asks to quit."""
    log = path.parent / INSTALL_LOG
    schedule_resume(path, log)
    flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    breakaway = getattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB', 0)
    command = [str(path), *setup_arguments(log)]
    try:
        try:
            subprocess.Popen(command, creationflags=flags | breakaway, close_fds=True, cwd=str(path.parent))
        except PermissionError:
            # A job that forbids breakaway refuses the flag; the installer still outlives this process.
            subprocess.Popen(command, creationflags=flags, close_fds=True, cwd=str(path.parent))
    except OSError:
        cancel_resume()  # Never leave a sign-in install behind for an installer that did not start.
        raise


class Attempts:
    """Installs tried per version, kept across openings: a version whose installer keeps failing is
    tried at most MAX_ATTEMPTS times, ATTEMPT_SPACING_SECONDS apart, never in a loop."""

    def __init__(self, folder, clock):
        self.path, self._clock = folder / ATTEMPTS_FILE, clock

    def _read(self):
        try: value = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError): return None
        if (isinstance(value, dict) and isinstance(value.get('versao'), str) and type(value.get('tentativas')) is int
                and type(value.get('ultima')) in {int, float}):
            return value
        return None

    def allowed(self, version):
        value = self._read()
        if value is None or value['versao'] != version: return True
        if value['tentativas'] >= MAX_ATTEMPTS: return False
        return not 0 <= self._clock() - value['ultima'] < ATTEMPT_SPACING_SECONDS

    def record(self, version):
        value = self._read()
        count = value['tentativas'] + 1 if value and value['versao'] == version else 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        partial = self.path.with_suffix('.tmp')
        partial.write_text(json.dumps({'versao': version, 'tentativas': count, 'ultima': self._clock()}),
                           encoding='utf-8')
        os.replace(partial, self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)


class Updater:
    def __init__(self, current_version, root, directory, *, safe_now, launch=launch_setup,
                 fetch=fetch_small, download=download_setup, power=power_ok, space=space_ok, clock=time.time,
                 clear_resume=clear_stale_resume, signer=signer):
        self._clear_resume, self._signer = clear_resume, signer
        self._current, self._root, self._folder = current_version, root, Path(directory) / 'atualizacao'
        self._safe_now, self._launch, self._fetch, self._download = safe_now, launch, fetch, download
        self._power, self._space, self._clock = power, space, clock
        self._attempts = Attempts(self._folder, clock)
        self._stop = threading.Event()
        self._thread = None

    def enabled(self):
        try: build = parse_version(self._current)[2]
        except UpdateError: return False
        return build > 0 and installed_folder(self._root) is not None

    def start(self):
        if not self.enabled() or self._thread is not None: return False
        try: self._clear_resume()
        except OSError: pass
        self._thread = threading.Thread(target=self._loop, name='collector-updater', daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    def _loop(self):
        try: remove_other_setups(self._folder, up_to=parse_version(self._current))  # Even offline.
        except OSError: pass
        # What the version before this one left in the program folder, once no installer writes there.
        folder = installed_folder(self._root)
        if folder is not None and not installer_running(): remove_leftovers(folder, self._current)
        if self._stop.wait(FIRST_CHECK_SECONDS): return
        while True:
            # After a started installer the app normally quits; still running later means it failed.
            try: result = 'started' if self.check_once() else 'current'
            except UpdateError as error: result = str(error)
            except Exception as error: result = type(error).__name__
            self._note(result)
            if self._stop.wait(CHECK_EVERY_SECONDS): return

    def _note(self, result):
        """Last check and its result only (no URL, path or content): what a support visit looks at."""
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            (self._folder / STATE_FILE).write_text(
                json.dumps({'em': int(self._clock()), 'versao': self._current, 'resultado': result}),
                encoding='utf-8')
        except OSError:
            pass

    def check_once(self):
        """True once the installer of a newer version was started."""
        manifest = read_manifest(self._fetch(MANIFEST_URL))
        version = manifest['versao']
        if parse_version(version) <= parse_version(self._current):
            remove_other_setups(self._folder)
            self._attempts.clear()
            return False
        if not self._attempts.allowed(version): raise UpdateError('waiting-after-failed-install')
        check_publisher(self._fetch(RELEASE_URL.format(version=version), RELEASE_LIMIT), manifest)
        remove_other_setups(self._folder, keep=manifest['arquivo'])
        if not self._space(self._folder, manifest['tamanho']): raise UpdateError('disk-full')
        setup = self._download(manifest, self._folder)
        # The Release's own hash only proves the download is whole; the signature proves who built it.
        # A workflow on any branch can write a Release as github-actions[bot], but only main can sign.
        if self._signer(setup) not in SIGNERS:
            setup.unlink(missing_ok=True)
            raise UpdateError('untrusted-signature')
        while not (self._safe_now() and self._power()):
            if self._stop.wait(SAFE_RETRY_SECONDS): return False
        self._attempts.record(version)
        self._launch(setup)
        return True
