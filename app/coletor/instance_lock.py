"""OS-released, per-user collector instance lock; no process-name termination."""
import os
from pathlib import Path
import threading
from .local_settings import user_settings_directory

# Per-session event: a second launch (shortcut, Start menu, Windows sign-in)
# asks the running Coletor to show its window instead of failing.
SHOW_EVENT = 'Local\\EcossistemaEscolar.ColetorFrequencia.Mostrar'
# Set by the installer (installer/Coletor.iss) before replacing the program:
# the running Coletor finishes the collection in flight and quits by itself.
QUIT_EVENT = 'Local\\EcossistemaEscolar.ColetorFrequencia.Encerrar'


def signal_running_instance(name=SHOW_EVENT):
    if os.name != 'nt': return False
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenEventW(0x0002, False, name)  # EVENT_MODIFY_STATE
    if not handle: return False
    try: return bool(kernel.SetEvent(handle))
    finally: kernel.CloseHandle(handle)


class ShowRequests:
    def __init__(self, name=SHOW_EVENT):
        self._handle = None
        self._stopped = False
        self._name = name
        if os.name == 'nt':
            import ctypes
            self._kernel = ctypes.windll.kernel32
            self._handle = self._kernel.CreateEventW(None, False, False, name)

    def listen(self, show):
        if not self._handle: return
        def wait():
            while not self._stopped:
                self._kernel.WaitForSingleObject(self._handle, 0xFFFFFFFF)
                if self._stopped: break
                try: show()
                except Exception: pass
        threading.Thread(target=wait, name='collector-requests-' + self._name.rsplit('.', 1)[-1].lower(),
                         daemon=True).start()

    def close(self):
        if not self._handle: return
        self._stopped = True
        self._kernel.SetEvent(self._handle)


def QuitRequests():
    return ShowRequests(QUIT_EVENT)


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
