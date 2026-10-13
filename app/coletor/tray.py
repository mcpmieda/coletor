"""Opt-in Windows tray adapter. Not imported or started by desktop.py.

The animation contract lives in tray_animation.py and runs without Windows.
No process is spawned, no startup task is registered and no business action is
implemented here. Native work starts only after enabled=True and start().
"""
import ctypes
from ctypes import wintypes
import logging
import math
import os
from pathlib import Path
import sys
import threading
from typing import Callable
import uuid

from .tray_animation import (
    AnimationController, AnimationPolicy, APP_TITLE, DEFAULT_ASSET_DIRECTORY,
    MIN_FRAME_INTERVAL, TrayPresentation, TrayPresenter, TrayState, resolve_icon_paths,
)

LOG = logging.getLogger(__name__)
WM_TRAY = 0x8000 + 41
WM_REFRESH = 0x8000 + 42
TIMER_ID = 1
ICON_ID = 1
ID_OPEN, ID_QUIT = 1001, 1002
NIN_KEYSELECT = 0x400 + 1
NIF_SHOWTIP = 0x80
NOTIFYICON_VERSION_4 = 4


class WindowsTray:
    """One owned, non-daemon message-loop thread and no animation/process worker.

    dispatch must enqueue a callback onto the application's UI thread and return
    immediately; it must not synchronously wait for that thread. on_quit remains
    responsible for shutting down the application's own resources and window.
    Creating this object is harmless on Linux. Calling start requires Windows,
    optional pywin32 and four base local ICOs. No dependency is auto-installed.
    """

    def __init__(self, *, on_open: Callable[[], None], on_quit: Callable[[], None],
                 dispatch: Callable[[Callable[[], None]], None], enabled: bool = False,
                 asset_directory: Path = DEFAULT_ASSET_DIRECTORY,
                 controller: AnimationController | None = None):
        if type(enabled) is not bool:
            raise TypeError("enabled deve ser booleano.")
        if not all(callable(item) for item in (on_open, on_quit, dispatch)):
            raise TypeError("Informe callbacks de abrir, sair e encaminhamento para a UI.")
        self.enabled = enabled
        self.controller = controller or AnimationController()
        self.asset_directory = Path(asset_directory)
        self._on_open, self._on_quit, self._dispatch = on_open, on_quit, dispatch
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._hwnd = None
        self._api = None
        self._con = None
        self._gui = None
        self._user32 = None
        self._presenter: TrayPresenter | None = None
        self._icons: dict[str, int] = {}
        self._registered_class = None
        self._instance = None
        self._timer_active = False
        self._last_error: str | None = None
        self._startup_error: Exception | None = None
        self._class_name = f"SmecelFoxTray.{os.getpid()}.{uuid.uuid4().hex}"
        self._taskbar_message = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self) -> str | None:
        """Generic diagnostic only; not a tooltip and never input/exception text."""
        with self._lock:
            return self._last_error

    def _record_error(self, code: str) -> None:
        with self._lock:
            changed = self._last_error != code
            self._last_error = code
        if changed:
            LOG.warning("Tray diagnostic: %s", code)

    def start(self, timeout: float = 5.0) -> None:
        if not self.enabled:
            raise RuntimeError("A bandeja está desativada. A integração precisa habilitá-la explicitamente.")
        if sys.platform != "win32":
            raise RuntimeError("O adaptador de bandeja requer Windows; o controlador é multiplataforma.")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("O tempo limite deve ser positivo.")
        with self._lock:
            if self._thread is not None or self._stop_requested.is_set():
                raise RuntimeError("Esta instância da bandeja já foi iniciada; crie outra após encerrá-la.")
            resolve_icon_paths(self.asset_directory)
            try:
                import win32api
                import win32con
                import win32gui
            except ImportError as exc:
                raise RuntimeError("O adaptador opcional requer pywin32 no ambiente Windows de desenvolvimento.") from exc
            self._api, self._con, self._gui = win32api, win32con, win32gui
            self._thread = threading.Thread(target=self._run, name="smecel-fox-tray", daemon=False)
            self._thread.start()
        if not self._ready.wait(timeout):
            self.stop(timeout)
            raise TimeoutError("A bandeja não terminou de iniciar dentro do prazo.")
        if self._startup_error is not None:
            self.stop(timeout)
            raise RuntimeError("Não foi possível iniciar a bandeja Windows.") from self._startup_error

    def stop(self, timeout: float = 5.0) -> None:
        """Idempotent shutdown; called from the owner thread, never self-join."""
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("O tempo limite não pode ser negativo.")
        self._stop_requested.set()
        with self._lock:
            thread, hwnd = self._thread, self._hwnd
        if hwnd and self._gui is not None:
            try:
                self._gui.PostMessage(hwnd, self._con.WM_CLOSE, 0, 0)
            except self._gui.error:
                # The owner may already be inside its finally/DestroyWindow.
                self._record_error("close-message-unavailable")
        if thread and thread is not threading.current_thread():
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError("A thread de bandeja ainda não encerrou; não inicie outra instância.")

    def set_state(self, state: TrayState | str, detail: str = "") -> None:
        if self.controller.set_state(state, detail):
            self._post_refresh()

    def set_policy(self, policy: AnimationPolicy) -> None:
        if self.controller.set_policy(policy):
            self._post_refresh()

    def _post_refresh(self) -> None:
        with self._lock:
            hwnd = self._hwnd
        if hwnd and not self._stop_requested.is_set():
            try:
                self._gui.PostMessage(hwnd, WM_REFRESH, 0, 0)
            except self._gui.error:
                self._record_error("refresh-message-unavailable")

    def _prepare_user32(self) -> None:
        # UINT_PTR and HANDLE are pointer-sized; never truncate on 64-bit Windows.
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
        self._user32.SetTimer.restype = ctypes.c_size_t
        self._user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
        self._user32.KillTimer.restype = wintypes.BOOL
        try:
            dpi = self._user32.SetThreadDpiAwarenessContext
            dpi.argtypes, dpi.restype = [ctypes.c_void_p], ctypes.c_void_p
            dpi(ctypes.c_void_p(-4))
        except AttributeError:
            pass

    def _run(self) -> None:
        try:
            self._prepare_user32()
            self._load_icons()
            self._taskbar_message = self._gui.RegisterWindowMessage("TaskbarCreated")
            wc = self._gui.WNDCLASS()
            self._instance = wc.hInstance = self._api.GetModuleHandle(None)
            wc.lpszClassName = self._class_name
            wc.lpfnWndProc = self._window_proc
            self._gui.RegisterClass(wc)
            self._registered_class = self._class_name
            # Hidden top-level window, not HWND_MESSAGE: receives TaskbarCreated broadcasts.
            hwnd = self._gui.CreateWindow(wc.lpszClassName, APP_TITLE, 0,
                                          0, 0, 0, 0, 0, 0, wc.hInstance, None)
            with self._lock:
                self._hwnd = hwnd
            self._presenter = TrayPresenter(self.controller, self)
            self._refresh()
            if not self._user32.SetTimer(hwnd, TIMER_ID, round(MIN_FRAME_INTERVAL * 1000), None):
                raise OSError("SetTimer failed")
            self._timer_active = True
            self._ready.set()
            if not self._stop_requested.is_set():
                self._gui.PumpMessages()
        except Exception as exc:
            self._startup_error = exc
            self._record_error("native-loop-failed")
        finally:
            self._cleanup()
            self._ready.set()

    def _load_icons(self) -> None:
        size = self._api.GetSystemMetrics(self._con.SM_CXSMICON)
        # Keep old handles alive until all replacements were loaded successfully.
        loaded, handles_by_path = {}, {}
        try:
            for key, path in resolve_icon_paths(self.asset_directory).items():
                if path not in handles_by_path:
                    handle = self._gui.LoadImage(0, str(path), self._con.IMAGE_ICON,
                                                 size, size, self._con.LR_LOADFROMFILE)
                    if not handle:
                        raise OSError("LoadImage returned no icon")
                    handles_by_path[path] = handle
                loaded[key] = handles_by_path[path]
        except Exception:
            for handle in handles_by_path.values():
                try:
                    self._gui.DestroyIcon(handle)
                except Exception:
                    self._record_error("partial-handle-cleanup-failed")
            raise
        previous, self._icons = self._icons, loaded
        for handle in set(previous.values()):
            try:
                self._gui.DestroyIcon(handle)
            except Exception:
                self._record_error("old-handle-cleanup-failed")

    def add(self, presentation: TrayPresentation) -> None:
        flags = self._gui.NIF_ICON | self._gui.NIF_MESSAGE | self._gui.NIF_TIP | NIF_SHOWTIP
        self._gui.Shell_NotifyIcon(self._gui.NIM_ADD, (
            self._hwnd, ICON_ID, flags, WM_TRAY, self._icons[presentation.frame_key], presentation.tooltip))
        try:
            # PyNOTIFYICONDATA index 7 is the uTimeout/uVersion union.
            self._gui.Shell_NotifyIcon(self._gui.NIM_SETVERSION,
                                      (self._hwnd, ICON_ID, 0, 0, 0, "", "", NOTIFYICON_VERSION_4))
        except Exception:
            self.remove()
            raise

    def modify(self, presentation: TrayPresentation) -> None:
        self._gui.Shell_NotifyIcon(self._gui.NIM_MODIFY, (
            self._hwnd, ICON_ID, self._gui.NIF_ICON | self._gui.NIF_TIP | NIF_SHOWTIP,
            WM_TRAY, self._icons[presentation.frame_key], presentation.tooltip))

    def remove(self) -> None:
        self._gui.Shell_NotifyIcon(self._gui.NIM_DELETE, (self._hwnd, ICON_ID))

    def _refresh(self, recovered: bool = False) -> None:
        if self._stop_requested.is_set() or self._presenter is None:
            return
        try:
            if recovered:
                self._presenter.taskbar_created()
            else:
                self._presenter.update()
        except Exception:
            # The next timer retries a failed add/modify, even with motion disabled.
            self._record_error("notification-area-unavailable")

    def _window_proc(self, hwnd, message, wparam, lparam):
        try:
            if message == self._con.WM_CLOSE:
                self._stop_requested.set()
                # Leave destruction to finally: DELETE the icon while HWND exists.
                self._gui.PostQuitMessage(0)
                return 0
            if message == self._con.WM_DESTROY:
                self._stop_requested.set()
                self._gui.PostQuitMessage(0)
                return 0
            if message == self._taskbar_message:
                try:
                    self._load_icons()  # Also emitted when the primary monitor's DPI changes.
                except Exception:
                    self._record_error("icon-scale-reload-failed")
                self._refresh(recovered=True)
                return 0
            if message == WM_REFRESH or (message == self._con.WM_TIMER and wparam == TIMER_ID):
                self._refresh()
                return 0
            if message == WM_TRAY:
                if self._stop_requested.is_set():
                    return 0
                event = lparam & 0xFFFF
                if event in (self._con.WM_LBUTTONDBLCLK, NIN_KEYSELECT):
                    self._dispatch(self._on_open)
                elif event in (self._con.WM_CONTEXTMENU, self._con.WM_RBUTTONUP):
                    self._show_menu()
                return 0
        except Exception:
            # Never let an exception unwind through a native Windows callback.
            self._record_error("native-callback-failed")
            return 0
        return self._gui.DefWindowProc(hwnd, message, wparam, lparam)

    def _show_menu(self) -> None:
        menu = self._gui.CreatePopupMenu()
        try:
            self._gui.AppendMenu(menu, self._con.MF_STRING | self._con.MF_DISABLED, 0,
                                 self.controller.snapshot().tooltip)
            self._gui.AppendMenu(menu, self._con.MF_SEPARATOR, 0, "")
            self._gui.AppendMenu(menu, self._con.MF_STRING, ID_OPEN, "&Abrir programa")
            self._gui.AppendMenu(menu, self._con.MF_STRING, ID_QUIT, "&Sair")
            position = self._gui.GetCursorPos()
            self._gui.SetForegroundWindow(self._hwnd)
            command = self._gui.TrackPopupMenu(menu, self._con.TPM_RETURNCMD | self._con.TPM_NONOTIFY,
                                              *position, 0, self._hwnd, None)
            if command == ID_OPEN:
                self._dispatch(self._on_open)
            elif command == ID_QUIT:
                self._dispatch(self._on_quit)
                self.stop()  # Posts WM_CLOSE; no self-join on the tray thread.
        finally:
            self._gui.DestroyMenu(menu)
            if not self._stop_requested.is_set():
                self._gui.PostMessage(self._hwnd, self._con.WM_NULL, 0, 0)
                self._gui.Shell_NotifyIcon(self._gui.NIM_SETFOCUS, (self._hwnd, ICON_ID))

    def _cleanup(self) -> None:
        # Best effort for each owned resource; one failure must not skip the rest.
        def release(action, error):
            try:
                action()
            except Exception:
                self._record_error(error)
        hwnd = self._hwnd
        if self._timer_active and hwnd:
            release(lambda: self._user32.KillTimer(hwnd, TIMER_ID), "timer-cleanup-failed")
        self._timer_active = False
        if self._presenter:
            release(self._presenter.close, "icon-remove-failed")
            self._presenter = None
        if hwnd and self._gui:
            release(lambda: self._gui.DestroyWindow(hwnd) if self._gui.IsWindow(hwnd) else None,
                    "window-cleanup-failed")
        with self._lock:
            self._hwnd = None
        for handle in set(self._icons.values()):
            release(lambda handle=handle: self._gui.DestroyIcon(handle), "handle-cleanup-failed")
        self._icons.clear()
        if self._registered_class:
            release(lambda: self._gui.UnregisterClass(self._registered_class, self._instance),
                    "class-cleanup-failed")
            self._registered_class = None
