import argparse

def main(argv=None):
    parser = argparse.ArgumentParser(description="Coletor de Frequência: prévia local, sem sincronização.")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--preview-server", action="store_true", help="Prévia no navegador de desenvolvimento, sem janela nativa.")
    actions.add_argument("--safe-removal", action="store_true", help="Remove a chave e solicita a retirada somente deste dispositivo; preserva pasta e configurações.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dev", action="store_true", help="Permite exclusivamente a origem Vite local 127.0.0.1:5173.")
    args = parser.parse_args(argv)
    if args.safe_removal:
        if args.dev:
            parser.error("--dev não se aplica à remoção segura")
        from .safe_removal import run
        return run()
    if args.preview_server:
        from .server import serve
        serve(port=args.port, dev=args.dev)
    else:
        from .desktop import run_desktop
        run_desktop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
