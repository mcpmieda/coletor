"""Whether this computer's collection was left active: a single non-secret flag.

Activating sets it; a local pause or logout clears it. Opening the program,
including at Windows sign-in, resumes collection only while it is set.
"""
import json
import os
from pathlib import Path
import tempfile
import threading

from .local_settings import user_settings_directory


class ResumeStore:
    def __init__(self, directory=None):
        self.path = (Path(directory) if directory is not None else user_settings_directory()) / 'collector-resume.json'
        self._lock = threading.Lock()

    def active(self):
        with self._lock:
            try:
                if self.path.is_symlink(): return False
                with self.path.open('rb') as file: raw = file.read(257)
                value = json.loads(raw.decode('utf-8')) if len(raw) <= 256 else None
            except (OSError, ValueError):
                return False
            return value == {'version': 1, 'resume': True}

    def set(self, resume):
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, name = tempfile.mkstemp(prefix='.resume-', suffix='.tmp', dir=self.path.parent)
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as file:
                        json.dump({'version': 1, 'resume': resume is True}, file)
                    os.replace(name, self.path)
                finally: Path(name).unlink(missing_ok=True)
            except OSError:
                pass
