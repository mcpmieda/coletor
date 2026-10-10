"""Windows desktop entry point, based on the Atualizador's Python/webview pattern.

No installer, scheduled task, tray agent, persistent browser profile or login is created.
The trusted local UI is the only page ever loaded into the privileged webview.
"""
from pathlib import Path
import sys
from .service import ROOT
from .desktop_api import DesktopApi

APP_USER_MODEL_ID = "EcossistemaEscolar.ColetorFrequenciaSmecel.Preview"


def run_desktop(callback=None, settings_directory=None):
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
    window = webview.create_window("Coletor de Frequência · Versão de teste", str(entry) + "#coletor-desktop", js_api=DesktopApi(settings_directory),
                          width=1240, height=820, min_size=(900, 620),
                          background_color="#faf7f8", text_select=True)
    # Ephemeral browser profile. Only the separate validated settings JSON persists.
    webview.start(func=callback, args=window, gui="edgechromium", debug=False, private_mode=True, http_server=True)

