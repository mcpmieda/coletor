"""Portable, non-installing launcher. Never writes diagnostic input to disk."""
import sys


def main():
    try:
        from .desktop import run_desktop
        run_desktop()
    except (Exception, SystemExit):
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                "Não foi possível abrir o coletor.\n\n"
                "Extraia toda a pasta antes de abrir. O Windows precisa do "
                "Microsoft Edge WebView2.\n\n"
                "Leia o arquivo LEIA-ME ou peça ajuda. Nenhum dado foi enviado.",
                "Coletor de Frequência", 0x10)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
