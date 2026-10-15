"""Windows desktop entry point, based on the Atualizador's Python/webview pattern.

No installer, scheduled task, persistent browser profile or login is created.
The trusted local UI is the only page ever loaded into the privileged webview.
"""
from pathlib import Path
import sys
from .service import ROOT
from .desktop_api import DesktopApi

APP_USER_MODEL_ID = "EcossistemaEscolar.ColetorFrequenciaSmecel"


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


def run_desktop(callback=None, settings_directory=None, *, access=None):
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
    from .instance_lock import CollectorInstance
    instance = CollectorInstance(settings_directory).acquire()
    api = DesktopApi(settings_directory, access=access)
    geometry = centered_window_geometry(primary_work_area())
    window = webview.create_window("Coletor de Frequência · 0.4.0", str(entry) + "#coletor-desktop", js_api=api,
                          **geometry, background_color="#faf7f8", text_select=True)
    # Ephemeral browser profile. Only the separate validated settings JSON persists.
    def opened(window):
        # pywebview starts func before creating the native form. Wait for its
        # public shown event; otherwise tray setup races window.native=None.
        if not window.events.shown.wait(20) or window.events.closed.is_set(): return
        from .tray_winforms import WindowsFormsTray
        tray = WindowsFormsTray(window, api._desktop_state)
        try:
            tray.start()
            api._tray = tray
        except Exception as error:
            tray._startup_error_type = type(error).__name__
            tray.stop()
        window._coletor_tray = tray  # Python QA only; not exposed to JavaScript.
        window.evaluate_js("window.dispatchEvent(new Event('coletortrayready'));true")
        if callback: callback(window)

    try:
        webview.start(func=opened, args=window, gui="edgechromium", debug=False, private_mode=True, http_server=True)
    finally:
        try:
            api._collector.shutdown()
        finally:
            try:
                api._access.shutdown()
            finally:
                try:
                    if api._tray is not None: api._tray.stop()
                finally: instance.close()

