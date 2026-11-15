"""Automatic update from this repository's GitHub Releases (owner request 15/11/2026).

Only an installed Coletor (Inno Setup uninstaller beside programa/) with a CI build number updates
itself. It reads a small manifest of the latest Release, downloads that version's installer from
the fixed Release URL, checks its size, SHA-256 and PE header, and runs it silently only when no
collection or report is running or due. The installer asks this app to quit (it finishes a run in
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
from urllib.parse import quote, urljoin, urlsplit

REPOSITORY = 'mcpmieda/coletor'
MANIFEST_NAME = 'atualizacao.json'
MANIFEST_URL = f'https://github.com/{REPOSITORY}/releases/latest/download/{MANIFEST_NAME}'
ALLOWED_HOSTS = frozenset({'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'})
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
    """Room for the download plus the installed copy it replaces (about three times the installer)."""
    import shutil
    probe = folder if folder.exists() else folder.parent
    try: return shutil.disk_usage(probe).free >= size * DISK_FACTOR
    except OSError: return False


def remove_other_setups(folder, keep=None):
    """Earlier downloads (an update already installed, or superseded) are not kept."""
    if not folder.is_dir(): return
    for path in folder.iterdir():
        if path.is_file() and path.name != keep and (path.suffix in {'.exe', '.part'}): path.unlink(missing_ok=True)


def resume_command(path):
    return subprocess.list2cmdline([str(path), *SETUP_ARGUMENTS, RESUME_ARGUMENT])


def schedule_resume(path):
    """If Windows turns off mid-install, the next sign-in runs the same installer again.

    The '!' keeps the RunOnce value until that run ends; the installer deletes it when it finishes
    (installer/Coletor.iss, RESUME_VALUE) and the reopened Coletor needs nothing else."""
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_ONCE_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, RESUME_VALUE, 0, winreg.REG_SZ, resume_command(path))


def launch_setup(path):
    """Start the installer on its own: it outlives this app, which it asks to quit."""
    schedule_resume(path)
    flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    breakaway = getattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB', 0)
    command = [str(path), *SETUP_ARGUMENTS]
    try:
        subprocess.Popen(command, creationflags=flags | breakaway, close_fds=True, cwd=str(path.parent))
    except PermissionError:
        # A job that forbids breakaway refuses the flag; the installer still outlives this process.
        subprocess.Popen(command, creationflags=flags, close_fds=True, cwd=str(path.parent))


class Updater:
    def __init__(self, current_version, root, directory, *, safe_now, launch=launch_setup,
                 fetch=fetch_small, download=download_setup, power=power_ok, space=space_ok):
        self._current, self._root, self._folder = current_version, root, Path(directory) / 'atualizacao'
        self._safe_now, self._launch, self._fetch, self._download = safe_now, launch, fetch, download
        self._power, self._space = power, space
        self._stop = threading.Event()
        self._thread = None
        self.launched = None  # The version whose installer was started.

    def enabled(self):
        try: build = parse_version(self._current)[2]
        except UpdateError: return False
        return build > 0 and installed_folder(self._root) is not None

    def start(self):
        if not self.enabled() or self._thread is not None: return False
        self._thread = threading.Thread(target=self._loop, name='collector-updater', daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    def _loop(self):
        if self._stop.wait(FIRST_CHECK_SECONDS): return
        while True:
            # After a started installer the app normally quits; still running later means it failed.
            try: self.check_once()
            except Exception: pass  # Offline, GitHub unavailable or a bad file: the next check tries again.
            if self._stop.wait(CHECK_EVERY_SECONDS): return

    def check_once(self):
        """True once the installer of a newer version was started."""
        manifest = read_manifest(self._fetch(MANIFEST_URL))
        if parse_version(manifest['versao']) <= parse_version(self._current):
            remove_other_setups(self._folder)
            return False
        remove_other_setups(self._folder, keep=manifest['arquivo'])
        if not self._space(self._folder, manifest['tamanho']): raise UpdateError('disk-full')
        setup = self._download(manifest, self._folder)
        while not (self._safe_now() and self._power()):
            if self._stop.wait(SAFE_RETRY_SECONDS): return False
        self._launch(setup)
        self.launched = manifest['versao']
        return True
