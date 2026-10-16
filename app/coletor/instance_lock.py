"""OS-released, per-user collector instance lock; no process-name termination."""
import os
from pathlib import Path
import threading
from .local_settings import user_settings_directory

# Per-session event: a second launch (shortcut, Start menu, Windows sign-in)
# asks the running Coletor to show its window instead of failing.
SHOW_EVENT = 'Local\\EcossistemaEscolar.ColetorFrequencia.Mostrar'


def signal_running_instance():
    if os.name != 'nt': return False
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenEventW(0x0002, False, SHOW_EVENT)  # EVENT_MODIFY_STATE
    if not handle: return False
    try: return bool(kernel.SetEvent(handle))
    finally: kernel.CloseHandle(handle)


class ShowRequests:
    def __init__(self):
        self._handle = None
        self._stopped = False
        if os.name == 'nt':
            import ctypes
            self._kernel = ctypes.windll.kernel32
            self._handle = self._kernel.CreateEventW(None, False, False, SHOW_EVENT)

    def listen(self, show):
        if not self._handle: return
        def wait():
            while not self._stopped:
                self._kernel.WaitForSingleObject(self._handle, 0xFFFFFFFF)
                if self._stopped: break
                try: show()
                except Exception: pass
        threading.Thread(target=wait, name='collector-show-requests', daemon=True).start()

    def close(self):
        if not self._handle: return
        self._stopped = True
        self._kernel.SetEvent(self._handle)


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
