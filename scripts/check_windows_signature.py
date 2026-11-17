"""The signature of the files a Release publishes, checked the way their users check it.

Run by the CI after signing. --expected is the certificate PowerShell reads from the signed
installer; the Coletor's own reader (app/coletor/updater.py, before an automatic update) and
"Instalar Coletor.exe" (before a first installation) must both name it, and both must refuse a
copy changed after signing. On main (--school) it must be the school's certificate, the only one
installed Coletors accept; any other build signs with a throwaway one.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from coletor import updater  # noqa: E402


def first_install_verdict(bootstrap, path):
    """0 the school's signature, 3 another intact one, 4 none (scripts/bootstrap/InstalarColetor.cs)."""
    return subprocess.run([str(bootstrap), '--conferir', str(path)], timeout=120, check=False).returncode


def check(setup, bootstrap, expected, school):
    accepted = expected in updater.SIGNERS
    if school and not accepted: raise RuntimeError('not-the-school-certificate')
    with tempfile.TemporaryDirectory(prefix='collector-signature-qa-') as folder:
        for path in (setup, bootstrap):
            if updater.signer(path) != expected: raise RuntimeError(f'signer-mismatch: {path.name}')
            if first_install_verdict(bootstrap, path) != (0 if accepted else 3):
                raise RuntimeError(f'first-install-verdict-mismatch: {path.name}')
            changed = Path(folder) / path.name
            raw = bytearray(path.read_bytes())
            raw[len(raw) // 3] ^= 0xFF  # One byte, well before the signature at the end of the file.
            changed.write_bytes(raw)
            if updater.signer(changed) is not None or first_install_verdict(bootstrap, changed) != 4:
                raise RuntimeError(f'changed-file-accepted: {path.name}')
    return 'school' if accepted else 'throwaway'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', type=Path, required=True)
    parser.add_argument('--bootstrap', type=Path, required=True)
    parser.add_argument('--expected', required=True, help='SHA-256 (hex) of the signing certificate')
    parser.add_argument('--school', action='store_true', help='the certificate must be the school\'s')
    parser.add_argument('--repository-copy', type=Path, required=True, help='instalador/Instalar Coletor.exe')
    args = parser.parse_args()
    if sys.platform != 'win32': raise SystemExit('windows-required')
    # The copy kept in the repository's instalador/ folder (owner request 17/11/2026: easy to find)
    # carries the school's signature in every build: only main can sign with it, so the file there
    # is always one a Release published, never one compiled by hand.
    if updater.signer(args.repository_copy.resolve()) not in updater.SIGNERS:
        raise RuntimeError('repository-copy-not-signed-by-the-school')
    print('signature-check-passed:', check(args.setup.resolve(), args.bootstrap.resolve(), args.expected.lower(), args.school))


if __name__ == '__main__':
    main()
