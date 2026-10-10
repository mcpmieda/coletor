import argparse

parser = argparse.ArgumentParser(description="Coletor de Frequência: prévia local, sem sincronização.")
parser.add_argument("--preview-server", action="store_true", help="Prévia no navegador de desenvolvimento, sem janela nativa.")
parser.add_argument("--port", type=int, default=8765)
parser.add_argument("--dev", action="store_true", help="Permite exclusivamente a origem Vite local 127.0.0.1:5173.")
args = parser.parse_args()
if args.preview_server:
    from .server import serve
    serve(port=args.port, dev=args.dev)
else:
    from .desktop import run_desktop
    run_desktop()
