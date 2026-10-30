"""Collector-owned DPAPI storage. No plaintext credentials or academic files.

Consent is native, not a JS checkbox. Entropy binds each blob to the application,
purpose, device and server generation. Windows protects it for this OS user.
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from .local_settings import user_settings_directory

MAX_QUEUE_BYTES = 64 * 1024 * 1024
MAX_QUEUE_ITEMS = 64
RETENTION_SECONDS = 7 * 24 * 60 * 60
# How long a queue must stay undecryptable (with the live binding) before it is
# set aside as belonging to an older device generation.
UNREADABLE_GRACE_SECONDS = 10 * 60
MAX_SESSION_BYTES = 1024 * 1024
MAX_SMALL_BYTES = 8 * 1024
PURPOSES = ('session', 'queue', 'consent', 'credential')
# What this computer last sent, one file per class diary and one for the school's weekly grid
# (owner decision 22/10/2026). Only a comparison aid: lost or unreadable means "send in full".
COPY_PURPOSE = re.compile(r'copy:(?:frequency-[1-9][0-9]{0,9}|schedule|student-report)')
MAX_COPY_BYTES = 32 * 1024 * 1024


class StorageError(ValueError):
    def __init__(self, code='PROTECTED_STORAGE_UNAVAILABLE'):
        self.code = code
        super().__init__(code)


def persistence_confirmation():
    if os.name != 'nt': return False
    return ctypes.windll.user32.MessageBoxW(None,
        'Autorizar o Coletor a lembrar a sessão do Smecel e guardar uma fila de frequência neste usuário do Windows?\n\n'
        'A sessão e os dados serão cifrados pelo Windows, usados apenas por este Coletor e removidos ao sair da conta. '
        'A fila tem limite de sete dias. Sem autorização, a sessão e a fila ficam somente na memória.',
        'Lembrar sessão e proteger fila — Coletor', 0x4 | 0x20 | 0x100) == 6


class Dpapi:
    def _crypt(self, value, entropy, decrypt=False):
        if os.name != 'nt': raise StorageError()
        class Blob(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]
        data_buffer = ctypes.create_string_buffer(value)
        entropy_buffer = ctypes.create_string_buffer(entropy)
        data = Blob(len(value), ctypes.cast(data_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        extra = Blob(len(entropy), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        result = Blob()
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                             ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        function.restype = wintypes.BOOL
        try:
            if not function(ctypes.byref(data), None, ctypes.byref(extra), None, None, 1, ctypes.byref(result)):
                raise StorageError()
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            if result.pbData: kernel.LocalFree(result.pbData)
            ctypes.memset(data_buffer, 0, len(data_buffer))
            ctypes.memset(entropy_buffer, 0, len(entropy_buffer))

    def protect(self, value, entropy): return self._crypt(value, entropy)
    def unprotect(self, value, entropy): return self._crypt(value, entropy, True)


class ProtectedStorage:
    def __init__(self, directory=None, *, crypto=None, consent=persistence_confirmation, clock=time.time):
        self.directory = (Path(directory) if directory is not None else user_settings_directory()) / 'protected-frequency-v2'
        self._crypto = crypto or Dpapi()
        self._consent, self._clock = consent, clock
        self.expired = 0  # Unreceipted batches dropped by retention, not yet logged.
        self.restored = 0  # Batches brought back from a set-aside queue, not yet logged.
        self._credential_summary = None
        self._unreadable_since = None
        self._binding = None
        self._enabled = False
        self._memory = {}
        self._lock = threading.RLock()

    def bind(self, device_id, generation):
        with self._lock:
            binding = f'{device_id}:{generation}'
            if self._binding is not None and self._binding != binding:
                # A server-side device/generation change is NOT an operator
                # discard and cannot erase a batch awaiting its receipt.
                # Inspect using the old DPAPI binding before modifying it.
                # Do not run queue() here: its expiry GC would mutate storage.
                pending = self._read('queue')
                if pending is not None:
                    if not isinstance(pending,list) or len(pending)>MAX_QUEUE_ITEMS or any(
                        not isinstance(item,dict) or type(item.get('createdAt')) not in {int,float}
                        or not isinstance(item.get('payload'),dict) for item in pending
                    ):
                        raise StorageError()
                    now=self._clock()
                    if any(item['createdAt']>now for item in pending):
                        raise StorageError()  # Clock rollback: preserve everything.
                    if any(now-item['createdAt']<=RETENTION_SECONDS for item in pending):
                        raise StorageError('PENDING_BATCHES')
                # The normal queue() expiry policy is already seven days.
                # Evaluate eligibility without writing: only the ordinary
                # binding cleanup may now retire previously expired entries.
                self.clear()
            self._binding = binding

    def enable(self):
        with self._lock:
            if self._binding is None: raise StorageError()
            # The answer is remembered for this device and server generation,
            # cifrado like the data it protects: opening with Windows must not
            # stop at a dialog nobody answers. Logout or revocation forget it.
            try:
                remembered = self._read('consent') == {'persistent': True}
            except StorageError:
                remembered = False
            if remembered:
                self._enabled = True
                return True
            self._enabled = bool(self._consent())
            if self._enabled: self._write_disk('consent', {'persistent': True})
            return self._enabled

    @property
    def persistent(self): return self._enabled

    def _entropy(self, purpose):
        if self._binding is None or not (purpose in PURPOSES or COPY_PURPOSE.fullmatch(purpose)): raise StorageError()
        return ('Ecossistema.Coletor.Protected.v2\0' + purpose + '\0' + self._binding).encode('utf-8')

    def _path(self, purpose):
        # "copy:frequency-13331" is stored as copy-frequency-13331.dpapi (no colon in Windows names).
        return self.directory / (purpose.replace(':', '-') + '.dpapi')

    def _read(self, purpose, path=None):
        if path is None and purpose in self._memory: return self._memory[purpose]
        path = path or self._path(purpose)
        limit = self._limit(purpose)
        try:
            if path.is_symlink(): raise StorageError()
            with path.open('rb') as file: raw = file.read(limit + 65537)
        except FileNotFoundError: return None
        if len(raw) > limit + 65536 or not raw.startswith(b'CFV2\0'): raise StorageError()
        try:
            value = json.loads(self._crypto.unprotect(raw[5:], self._entropy(purpose)))
            if not isinstance(value, dict) or value.get('version') != 2 or value.get('binding') != self._binding:
                raise StorageError()
            return value['value']
        except StorageError: raise
        except Exception: raise StorageError() from None

    @staticmethod
    def _limit(purpose):
        if purpose == 'session': return MAX_SESSION_BYTES
        if purpose.startswith('copy:'): return MAX_COPY_BYTES
        return MAX_QUEUE_BYTES if purpose == 'queue' else MAX_SMALL_BYTES

    def _write(self, purpose, value):
        if not self._enabled:
            self._encode(purpose, value)
            self._memory[purpose] = value
            return
        self._write_disk(purpose, value)

    def _encode(self, purpose, value):
        raw = json.dumps({'version': 2, 'binding': self._binding, 'value': value},
                         ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(raw) > self._limit(purpose): raise StorageError('PROTECTED_STORAGE_LIMIT')
        return raw

    def _write_disk(self, purpose, value):
        raw = self._encode(purpose, value)
        encrypted = b'CFV2\0' + self._crypto.protect(raw, self._entropy(purpose))
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink(): raise StorageError()
        fd, name = tempfile.mkstemp(prefix='.protected-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(encrypted)
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, self._path(purpose))
            self._memory.pop(purpose, None)
        finally: Path(name).unlink(missing_ok=True)

    def load_session(self):
        with self._lock:
            state = self._read('session')
            if state is not None:
                if not isinstance(state, dict) or set(state) != {'cookies', 'origins'}:
                    raise StorageError()
                if not isinstance(state['cookies'], list) or not isinstance(state['origins'], list): raise StorageError()
                # Restore only the explicitly allowed source; other cookies or
                # origin data cannot introduce a second identity provider.
                if any(c.get('domain') not in {'www.smecel.com.br', '.smecel.com.br', 'smecel.com.br'} for c in state['cookies']):
                    raise StorageError()
                if any(o.get('origin') != 'https://www.smecel.com.br' for o in state['origins']): raise StorageError()
            return state

    def save_session(self, state):
        with self._lock:
            if (not isinstance(state, dict) or set(state) != {'cookies', 'origins'}
                    or not isinstance(state['cookies'], list) or not isinstance(state['origins'], list)
                    or any(not isinstance(c, dict) or c.get('domain') not in {'www.smecel.com.br', '.smecel.com.br', 'smecel.com.br'} for c in state['cookies'])
                    or any(not isinstance(o, dict) or o.get('origin') != 'https://www.smecel.com.br' for o in state['origins'])):
                raise StorageError()
            self._write('session', state)
            self.load_session()  # Validate even memory-only state.

    def queue(self):
        with self._lock:
            values = self._read('queue') or []
            if not isinstance(values, list) or len(values) > MAX_QUEUE_ITEMS: raise StorageError()
            if any(not isinstance(v, dict) or set(v) != {'createdAt', 'payload'} or
                   type(v['createdAt']) not in {int, float} or not isinstance(v['payload'], dict) for v in values): raise StorageError()
            now = self._clock()
            # A Windows clock rollback must not silently discard an unreceipted
            # batch. Keep the encrypted queue intact until time is corrected.
            if any(v['createdAt'] > now for v in values): raise StorageError()
            fresh = [v for v in values if now - v['createdAt'] <= RETENTION_SECONDS]
            if fresh != values:
                self._write('queue', fresh)
                # Never silent: the runtime records how many expired unreceipted.
                self.expired += len(values) - len(fresh)
            return fresh

    def take_expired(self):
        with self._lock:
            count, self.expired = self.expired, 0
            return count

    def quarantine_unreadable_queue(self):
        """With the current online binding in place, a queue that still cannot
        be decrypted belongs to an older device generation: it can never be read
        or receipted again. Move it aside (kept, encrypted) instead of blocking
        collection or asking someone to discard it. Returns True if moved.

        A single failure is never enough (DPAPI can fail for a moment at logon,
        an antivirus can hold the file): the queue must stay unreadable for
        UNREADABLE_GRACE_SECONDS. Set-aside files are removed after the queue's
        own retention and by clear() (logout, safe removal)."""
        with self._lock:
            self._purge_quarantine(older_than=RETENTION_SECONDS)
            self.restored += self._reintegrate_quarantine()
            path = self.directory / 'queue.dpapi'
            if self._binding is None or 'queue' in self._memory or not path.exists() or path.is_symlink():
                self._unreadable_since = None
                return False
            try:
                self._read('queue')
                self._unreadable_since = None
                return False
            except StorageError:
                now = self._clock()
                if self._unreadable_since is None: self._unreadable_since = now
                if now - self._unreadable_since < UNREADABLE_GRACE_SECONDS: return False
                try:
                    # The name carries when it was set aside (the collector's clock).
                    path.replace(self.directory / f'queue-unreadable-{int(now)}.dpapi')
                except OSError:
                    return False  # Held by another process: try again later.
                self._unreadable_since = None
                return True
            except OSError:
                return False

    def _quarantine_files(self):
        try: return [p for p in sorted(self.directory.glob('queue-unreadable-*.dpapi')) if not p.is_symlink()]
        except OSError: return []

    def quarantined(self):
        """Set-aside queues still waiting (safe removal treats them as pending)."""
        with self._lock: return len(self._quarantine_files())

    def _reintegrate_quarantine(self):
        """A set-aside queue that decrypts again with the live binding belongs
        to this device after all (DPAPI recovered): its batches go back to the
        queue for the normal receipt check. Returns how many came back."""
        if self._binding is None: return 0
        restored = 0
        for item in self._quarantine_files():
            try: rows = self._read('queue', path=item)
            except (StorageError, OSError): continue
            if not isinstance(rows, list): continue
            try:
                current = self._read('queue') or []
            except StorageError:
                continue  # The live queue itself is unreadable: retry later.
            known = {v['payload'].get('requestId') for v in current}
            back = [v for v in rows if isinstance(v, dict) and isinstance(v.get('payload'), dict)
                    and v['payload'].get('requestId') not in known]
            if len(current) + len(back) > MAX_QUEUE_ITEMS: continue
            if back: self._write('queue', [*current, *back])
            try: item.unlink()
            except OSError: continue
            restored += len(back)
        return restored

    def _purge_quarantine(self, older_than=None):
        """Retention (7 days, like the queue) or an explicit decision (clear,
        confirmed discard). Expired set-aside files are counted and logged."""
        now = self._clock()
        for item in self._quarantine_files():
            try:
                stamp = item.stem.rsplit('-', 1)[-1]
                since = int(stamp) if stamp.isdigit() and len(stamp) >= 9 else item.stat().st_mtime
                if older_than is None or now - since > older_than:
                    item.unlink()
                    if older_than is not None: self.expired += 1
            except OSError:
                pass

    def recovery_status(self):
        """Minimal LOCAL metadata, even if an old DPAPI generation is unreadable.

        Never return marks, student data, credentials, identifiers or source HTML.
        An unreadable queue is treated as present until native confirmation.
        """
        with self._lock:
            path=self.directory/'queue.dpapi'
            if self.directory.is_symlink(): raise StorageError()
            if path.is_symlink(): raise StorageError()
            on_disk=path.exists()
            if on_disk and self._binding is None:
                # Unreadable for now, because the live access has not opened it
                # yet: an authorized window waits (bound=False); a revoked
                # device can only recover it explicitly.
                return {'pending':True,'count':None,'oldest':None,'newest':None,'unreadable':True,'bound':False}
            try:
                rows=self._read('queue')
                if rows is not None and (not isinstance(rows,list) or len(rows)>MAX_QUEUE_ITEMS
                    or any(not isinstance(v,dict) or type(v.get('createdAt')) not in {int,float}
                           or not isinstance(v.get('payload'),dict) for v in rows)):
                    raise StorageError()
            except StorageError:
                if not on_disk and 'queue' not in self._memory: raise
                return {'pending':True,'count':None,'oldest':None,'newest':None,'unreadable':True}
            values=rows or []
            dates=[v['createdAt'] for v in values]
            return {'pending':bool(values) or on_disk and rows is None,
                    'count':len(values) if rows is not None else None,
                    'oldest':min(dates) if dates else None,
                    'newest':max(dates) if dates else None,'unreadable':False}

    def discard_confirmed_local_queue(self):
        """Explicit native-confirmed recovery; remove ONLY this collector's queue.

        No network or device key is required after authorization was revoked.
        Neither session nor credentials nor another app's files are touched.
        """
        with self._lock:
            path=self.directory/'queue.dpapi'
            if self.directory.is_symlink() or path.is_symlink(): raise StorageError()
            # Unlink is atomic on Windows; a deletion error must not be reported
            # as success. Keep other protected purposes intact.
            path.unlink(missing_ok=True)
            self._memory.pop('queue',None)
            self._purge_quarantine()  # The same explicit decision covers set-aside queues.

    def enqueue(self, payload):
        with self._lock:
            values = self.queue()
            existing = next((v for v in values if v['payload'].get('requestId') == payload.get('requestId')), None)
            if existing:
                if existing['payload'] != payload: raise StorageError('QUEUE_REQUEST_CONFLICT')
                return
            if len(values) >= MAX_QUEUE_ITEMS: raise StorageError('PROTECTED_STORAGE_LIMIT')
            self._write('queue', [*values, {'createdAt': self._clock(), 'payload': payload}])

    def acknowledge(self, request_id):
        with self._lock:
            remaining = [v for v in self.queue() if v['payload'].get('requestId') != request_id]
            if remaining:
                self._write('queue', remaining)
            else:
                # A successfully reconciled last receipt must not leave an
                # unreadable (without old generation entropy) encrypted empty
                # queue that blocks a fresh safe-removal process. Unlink is
                # atomic and failures propagate; never remove nonempty queues.
                self.discard_confirmed_local_queue()

    def load_copy(self, name):
        """The last copy saved under this name, or None when there is none or it cannot be read
        (formatted or restored computer, cleared data, another Windows user or device generation):
        the caller then sends in full and saves a new one."""
        purpose = 'copy:' + name
        if not COPY_PURPOSE.fullmatch(purpose): raise StorageError()
        with self._lock:
            try: value = self._read(purpose)
            except StorageError: return None
            return value if isinstance(value, dict) else None

    def save_copy(self, name, value):
        """Replace the copy with the data just confirmed by the server. Memory only when the operator
        did not allow persistence; too large raises PROTECTED_STORAGE_LIMIT."""
        purpose = 'copy:' + name
        if not COPY_PURPOSE.fullmatch(purpose) or not isinstance(value, dict): raise StorageError()
        with self._lock: self._write(purpose, value)

    def save_credential(self, email, password):
        """Explicit operator action: the Smecel login is written cifrado by
        Windows for this user and device, and never returned to the window."""
        with self._lock:
            if (not isinstance(email, str) or not 3 <= len(email.strip()) <= 254 or '@' not in email
                    or any(c.isspace() for c in email.strip())
                    or not isinstance(password, str) or not 1 <= len(password) <= 256 or chr(0) in password):
                raise StorageError('SOURCE_CREDENTIAL_INVALID')
            self._credential_summary = None
            self._write_disk('credential', {'email': email.strip(), 'password': password})

    def load_credential(self):
        with self._lock:
            try:
                value = self._read('credential')
            except StorageError:
                return None
            if (not isinstance(value, dict) or set(value) != {'email', 'password'}
                    or not all(isinstance(value[k], str) and value[k] for k in value)):
                return None
            return value

    def credential_status(self):
        """Masked summary, cached per binding: the tray asks every few seconds
        and must not decrypt the password each time. Saving, clearing or a new
        binding forgets the cache."""
        with self._lock:
            if self._credential_summary is not None and self._credential_summary[0] == self._binding:
                return dict(self._credential_summary[1])
        value = self.load_credential()
        if value is None: summary = {'saved': False}
        else:
            local, _, domain = value['email'].partition('@')
            summary = {'saved': True, 'account': (local[:2] + '•••@' + domain) if domain else '•••'}
        with self._lock: self._credential_summary = (self._binding, summary)
        return dict(summary)

    def clear_credential(self):
        with self._lock:
            self._credential_summary = None
            self._memory.pop('credential', None)
            (self.directory / 'credential.dpapi').unlink(missing_ok=True)

    def clear(self):
        with self._lock:
            self._credential_summary = None
            self._memory.clear()
            self._enabled = False
            # Only the owned files; no recursive deletion or other app paths.
            for purpose in PURPOSES:
                (self.directory / (purpose + '.dpapi')).unlink(missing_ok=True)
            try: copies = [p for p in self.directory.glob('copy-*.dpapi') if not p.is_symlink()]
            except OSError: copies = []
            for item in copies: item.unlink(missing_ok=True)
            # Set-aside queues are NOT removed here: logout is no proof they were
            # receipted. They come back if readable, or expire with the retention.
