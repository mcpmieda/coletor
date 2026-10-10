"""Windows desktop entry point, based on the Atualizador's Python/webview pattern.

No installer, scheduled task, tray agent, persistent profile or login is created.
The trusted local UI is the only page ever loaded into the privileged webview.
"""
from pathlib import Path
import sys
from .service import PreviewApi, ROOT

APP_USER_MODEL_ID = "EcossistemaEscolar.ColetorFrequenciaSmecel.Preview"


def run_desktop():
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
    webview.create_window("Coletor de Frequência · Prévia local", str(entry), js_api=PreviewApi(),
                          width=1240, height=820, min_size=(900, 620),
                          background_color="#f6f7f8", text_select=True)
    # Ephemeral profile. Do not copy the original app's private_mode=False.
    webview.start(gui="edgechromium", debug=False, private_mode=True, http_server=True)
