"""OS-released, per-user collector instance lock; no process-name termination."""
import os
from pathlib import Path
from .local_settings import user_settings_directory


class CollectorInstance:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else user_settings_directory()
        self.file = None

    def acquire(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file = (self.directory / 'collector-instance.lock').open('a+b')
        try:
            self.file.seek(0)
            if self.file.read(1) == b'':
                self.file.write(b'\0')
                self.file.flush()
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise RuntimeError('O Coletor já está aberto neste usuário do Windows.') from None
        return self

    def close(self):
        if self.file is not None:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()
            self.file = None
