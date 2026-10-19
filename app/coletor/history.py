"""Local operation history of this computer: what happened and when.

Only operational facts are written: event kind, sanitized code, class label and
counts. Never student names, marks, diaries, credentials or server payloads.
Entries older than 30 days, and anything beyond the last 2000, are dropped.
"""
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from .local_settings import user_settings_directory

RETENTION_SECONDS = 30 * 24 * 60 * 60
MAX_ENTRIES = 2000
COMPACT_SLACK = 500  # Appended lines tolerated before rewriting the file.
MAX_READ_BYTES = 2 * 1024 * 1024
KINDS = {'activated', 'paused', 'resumed', 'collection-started', 'class-sent', 'collection-finished',
         'failure', 'smecel-login', 'smecel-login-failed', 'access-required', 'started', 'superseded', 'late-start', 'late-cancelled', 'queue-quarantined', 'queue-expired'}


class CollectorHistory:
    def __init__(self, directory=None, *, clock=time.time):
        self.path = (Path(directory) if directory is not None else user_settings_directory()) / 'collector-history.jsonl'
        self._clock = clock
        self._lock = threading.Lock()
        self._lines = None  # Lines in the file, counted once, then tracked.

    def _read(self):
        try:
            if self.path.is_symlink(): return []
            with self.path.open('rb') as file: raw = file.read(MAX_READ_BYTES + 1)
        except FileNotFoundError: return []
        except OSError: return []
        entries = []
        for line in raw[:MAX_READ_BYTES].decode('utf-8', 'ignore').splitlines():
            try: value = json.loads(line)
            except ValueError: continue
            if isinstance(value, dict) and value.get('kind') in KINDS and type(value.get('at')) in {int, float}:
                entries.append(value)
        return entries

    def record(self, kind, *, code=None, label=None, sent=None, unresolved=None, conflicts=None,
               read_ms=None, send_ms=None):
        """Append one fact; a failure to write never interrupts collection."""
        if kind not in KINDS: return
        entry = {'at': round(self._clock(), 3), 'kind': kind}
        if isinstance(code, str) and code: entry['code'] = code[:60]
        if isinstance(label, str) and label: entry['label'] = ' '.join(label.split())[:120]
        for key, value in (('sent', sent), ('unresolved', unresolved), ('conflicts', conflicts),
                           ('readMs', read_ms), ('sendMs', send_ms)):
            if type(value) is int and value >= 0: entry[key] = value
        with self._lock:
            try:
                # O(1) per event: append one line. The whole file is rewritten
                # only when it has grown well past the limit (compaction).
                if self._lines is None: self._lines = len(self._read())
                if self._lines < MAX_ENTRIES + COMPACT_SLACK and not self.path.is_symlink():
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open('a', encoding='utf-8', newline='\n') as file:
                        file.write(json.dumps(entry, ensure_ascii=False, separators=(',', ':')) + '\n')
                    self._lines += 1
                    return
                cutoff = self._clock() - RETENTION_SECONDS
                kept = [e for e in self._read() if e['at'] >= cutoff][-(MAX_ENTRIES - 1):]
                kept.append(entry)
                self._lines = len(kept)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, name = tempfile.mkstemp(prefix='.history-', suffix='.tmp', dir=self.path.parent)
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as file:
                        file.writelines(json.dumps(e, ensure_ascii=False, separators=(',', ':')) + '\n' for e in kept)
                    os.replace(name, self.path)
                finally: Path(name).unlink(missing_ok=True)
            except OSError:
                pass

    def recent(self, limit=100):
        with self._lock:
            cutoff = self._clock() - RETENTION_SECONDS
            entries = [e for e in self._read() if e['at'] >= cutoff]
        return list(reversed(entries[-limit:]))

    def clear(self):
        with self._lock:
            self.path.unlink(missing_ok=True)
            self._lines = 0
