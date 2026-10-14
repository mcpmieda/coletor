"""Windows desktop entry point, based on the Atualizador's Python/webview pattern.

No installer, scheduled task, persistent browser profile or login is created.
The trusted local UI is the only page ever loaded into the privileged webview.
"""
from pathlib import Path
import sys
from .service import ROOT
from .desktop_api import DesktopApi

APP_USER_MODEL_ID = "EcossistemaEscolar.ColetorFrequenciaSmecel.Preview"


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
    api = DesktopApi(settings_directory, access=access)
    window = webview.create_window("Coletor de Frequência · Versão de teste", str(entry) + "#coletor-desktop", js_api=api,
                          width=1240, height=820, min_size=(900, 620),
                          background_color="#faf7f8", text_select=True)
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
            api._manual_session.close()
        finally:
            try:
                api._access.shutdown()
            finally:
                if api._tray is not None: api._tray.stop()

