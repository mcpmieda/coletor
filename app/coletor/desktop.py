"""Windows desktop entry point, based on the Atualizador's Python/webview pattern.

No scheduled task, persistent browser profile or login is created here. An installed copy
checks the repository's Releases and updates itself (updater.py).
The trusted local UI is the only page ever loaded into the privileged webview.
"""
import os
import sys
import threading
from . import __version__
from .service import ROOT
from .desktop_api import DesktopApi

APP_USER_MODEL_ID = "EcossistemaEscolar.ColetorFrequenciaSmecel"
# An update waits this long for the collection in flight (installer/Coletor.iss
# waits a little longer before stopping the processes as a last resort).
EXIT_COLLECTION_WAIT = 15 * 60


def centered_window_geometry(work_area, width=1240, height=820, minimum=(900, 620)):
    """Fit within the primary monitor's usable desktop and center the form.

    Coordinates use the same Win32 logical desktop units as pywebview. Allow
    smaller windows on compact screens rather than opening outside the display.
    """
    left, top, right, bottom = work_area
    available_width, available_height = right - left, bottom - top
    if available_width <= 0 or available_height <= 0:
        raise ValueError("Invalid primary monitor work area")
    usable_width = max(1, available_width - min(32, available_width // 10))
    usable_height = max(1, available_height - min(32, available_height // 10))
    fitted_width, fitted_height = min(width, usable_width), min(height, usable_height)
    return {
        "width": fitted_width, "height": fitted_height,
        "x": left + (available_width - fitted_width) // 2,
        "y": top + (available_height - fitted_height) // 2,
        "min_size": (min(minimum[0], fitted_width), min(minimum[1], fitted_height)),
    }


def primary_work_area():
    import ctypes
    from ctypes import wintypes
    rect = wintypes.RECT()
    if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
        return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)


def finish_native_form(window):
    """Finish real WinForms placement after DPI awareness and show event."""
    from System import Action
    from System.Drawing import Icon
    from System.Windows.Forms import Screen
    from .tray_animation import DEFAULT_ASSET_DIRECTORY

    def place_and_brand():
        form = window.native
        area = Screen.PrimaryScreen.WorkingArea
        form.Left = int(area.Left + (area.Width - form.Width) // 2)
        form.Top = int(area.Top + (area.Height - form.Height) // 2)
        icon = Icon(str(DEFAULT_ASSET_DIRECTORY / "fox-idle.ico"))
        form.Icon = icon
        window._coletor_native_icon = icon

    window.native.Invoke(Action(place_and_brand))


def quit_for_update(window, api, wait=EXIT_COLLECTION_WAIT, ready=None):
    """Installer request: let the collection in flight end, then quit like Encerrar coletor.

    A request that arrives while the program is still opening waits for the
    opening to end (ready): destroying the window before the clock icon exists
    left the icon's message loop running and the process never exited.
    """
    api._collector.finish_for_exit(wait)
    if ready is not None: ready.wait(90)
    else: window.events.shown.wait(60)
    tray = api._tray
    if tray is not None:
        tray._invoke(tray._quit)
        if window.events.closed.wait(10): return
    window.destroy()


def window_profile(directory):
    """The folder of the window's browser profile: a new one at each opening, inside a temporary
    folder that is this Coletor's alone, where what its earlier openings left is removed first.

    Left to pywebview, private mode makes the new folder loose in %TEMP% and deletes it when the
    window closes; when WebView2 was slow to leave, the folder stayed there for good (62 of them on
    one computer since October 2026). The parent is named after `directory` (one Coletor runs per
    data folder, so nobody else's profile is ever there), never inside it: the data folder holds
    settings only. Never the same folder twice: an opening right after a closing (an update) would
    share it with the browser still leaving. None when the folder cannot be made: pywebview then
    uses a temporary one of its own, as before."""
    import hashlib
    import shutil
    import tempfile
    import uuid
    from pathlib import Path
    owner = hashlib.sha256(str(Path(directory).resolve()).lower().encode("utf-8")).hexdigest()[:16]
    parent = Path(tempfile.gettempdir()) / f"coletor-janela-{owner}"
    try:
        if parent.is_symlink() or parent.is_junction(): return None
        shutil.rmtree(parent, ignore_errors=True)  # All but what a browser still leaving holds.
        profile = parent / uuid.uuid4().hex
        profile.mkdir(parents=True)
    except OSError:
        return None
    return str(profile)


def run_desktop(callback=None, settings_directory=None, *, access=None, background=False):
    if sys.platform != "win32":
        raise SystemExit("A janela desktop requer Windows. Use --preview-server para testar a prévia neste sistema.")
    entry = ROOT / "ui/dist/index.html"
    if not entry.is_file():
        raise SystemExit("Interface não compilada. Execute npm ci e npm run build na pasta ui.")
    try:
        import webview
    except ImportError:
        raise SystemExit("Instale a dependência de desenvolvimento desktop indicada no README.") from None
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    from .instance_lock import CollectorInstance, QuitRequests, ShowRequests, signal_running_instance
    try:
        instance = CollectorInstance(settings_directory).acquire()
    except RuntimeError:
        # Already open (perhaps started with Windows, hidden in the tray): show it.
        if signal_running_instance(): return
        raise
    show_requests = ShowRequests()
    api = DesktopApi(settings_directory, access=access)
    geometry = centered_window_geometry(primary_work_area())
    window = webview.create_window(f"Coletor · {__version__}", str(entry) + "#coletor-desktop", js_api=api,
                          **geometry, background_color="#faf7f8", text_select=True)
    from .local_settings import user_settings_directory
    from .updater import Updater
    directory = settings_directory or user_settings_directory()
    updater = Updater(__version__, ROOT, directory,
                      safe_now=api._update_allowed, idle_now=api._collector.idle)
    api._updater = updater  # Ajustes > Verificar atualizações.
    quit_requests = QuitRequests()
    ready = threading.Event()  # Set once opened() has finished (clock icon in place or failed).
    quit_requests.listen(lambda: quit_for_update(window, api, ready=ready))
    # Ephemeral browser profile. Only the separate validated settings JSON persists.
    def opened(window):
        try: open_window(window)
        finally: ready.set()

    def open_window(window):
        # pywebview starts func before creating the native form. Wait for its
        # public shown event; otherwise tray setup races window.native=None.
        if not window.events.shown.wait(20) or window.events.closed.is_set(): return
        finish_native_form(window)
        from .tray_winforms import WindowsFormsTray
        tray = WindowsFormsTray(window, api._desktop_state)
        try:
            tray.start()
            api._attach_tray(tray)
        except Exception as error:
            tray._startup_error_type = type(error).__name__
            tray.stop()
        window._coletor_tray = tray  # Python QA only; not exposed to JavaScript.
        window.evaluate_js("window.dispatchEvent(new Event('coletortrayready'));true")
        show_requests.listen(lambda: tray._invoke(tray._open) if api._tray is not None else window.restore())
        if background:
            # Opened with Windows: stay beside the clock; the fox opens the window.
            if api._tray is None or "error" in tray.hide(): window.minimize()
        api._start_resume()
        updater.start()
        if callback: callback(window)

    try:
        profile = window_profile(directory)
        webview.start(func=opened, args=window, gui="edgechromium", debug=False, private_mode=True, http_server=True,
                      storage_path=profile)
    finally:
        # pywebview deleted the profile when the window closed: its parent goes too, once empty.
        try:
            if profile: os.rmdir(os.path.dirname(profile))
        except OSError: pass
        updater.stop()
        try:
            api._collector.shutdown()
        finally:
            try:
                api._access.shutdown()
            finally:
                try:
                    if api._tray is not None: api._tray.stop()
                finally:
                    show_requests.close()
                    quit_requests.close()
                    instance.close()

