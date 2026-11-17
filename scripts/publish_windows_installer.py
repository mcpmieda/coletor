"""Stage a Windows-tested installer as the files of one GitHub Release.

Owner request 15/11/2026: installers no longer live in the repository (Git LFS kept every build
forever). Each build becomes a Release with four files: the installer, its .sha256, atualizacao.json,
which installed Coletors read to update themselves (app/coletor/updater.py), and "Instalar Coletor.exe",
which installs the newest Release on a new computer (scripts/bootstrap/), built and signed by the same run.

This tool only *copies* an already validated CI artifact. It never runs the EXE, contacts the
internet or accesses real student records. The workflow creates the Release with these files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import struct

SOURCE = re.compile(r"ColetorFrequencia-(\d+\.\d+\.\d+)-windows-x64-setup-candidato\.exe\Z")
FULL_SHA = re.compile(r"[0-9a-f]{40}\Z")
MANIFEST = 'atualizacao.json'
# No space: Release assets turn spaces into dots. Always at releases/latest/download/Instalar-Coletor.exe.
BOOTSTRAP = 'Instalar-Coletor.exe'
BOOTSTRAP_MINIMUM = 8_000


# What goes into the installed program (scripts/build_windows_portable.py, installer/Coletor.iss) or
# into "Instalar Coletor.exe". Only a change here becomes a new Release: every installed Coletor
# reinstalls each one.
BUNDLE_PATHS = re.compile(
    r'(app/|ui/|installer/|scripts/bootstrap/|scripts/build_windows_portable\.py\Z'
    r'|requirements-windows-(build|portable)\.txt\Z|docs/PORTABLE_LEIA_ME\.txt\Z)')


def touches_bundle(paths) -> bool:
    return any(BUNDLE_PATHS.match(path) for path in paths if path)


def publish_decision(*, newer_head_changes, since_release_changes) -> str:
    """Whether the build of this run becomes a Release.

    newer_head_changes: paths changed between this run's commit and main's head (empty when equal).
    since_release_changes: paths changed between the latest Release's commit and this run's commit,
    or None when there is no Release yet."""
    if touches_bundle(newer_head_changes):
        return 'newer-build-follows'  # The newer commit's own run publishes the newer program.
    if since_release_changes is not None and not touches_bundle(since_release_changes):
        return 'program-unchanged'
    return 'publish'


def asset_name(version: str) -> str:
    # Release assets turn spaces into dots, so no space (the local copy keeps "COLETOR v…").
    return f'COLETOR-v{version}.exe'


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_pe(path: Path, minimum_bytes: int = 1_000_000) -> None:
    """Shallow check for a real nonempty PE, not a replacement for native CI."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size < minimum_bytes:
        raise ValueError('missing-or-undersized-Windows-setup')
    with path.open('rb') as file:
        header = file.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise ValueError('not-Windows-PE-MZ')
        location = struct.unpack_from('<I', header, 0x3C)[0]
        if not 64 <= location <= 65536 or location + 4 > path.stat().st_size:
            raise ValueError('invalid-Windows-PE-offset')
        file.seek(location)
        if file.read(4) != b'PE\x00\x00':
            raise ValueError('not-Windows-PE-signature')


def original_setup(artifact_dir: Path, *, minimum_bytes: int) -> tuple[Path, str, str]:
    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
        raise ValueError('artifact-directory-missing')
    files = sorted(artifact_dir.iterdir())
    if any(not p.is_file() or p.is_symlink() for p in files):
        raise ValueError('artifact-must-contain-only-files')
    installers = [p for p in files if SOURCE.fullmatch(p.name)]
    if len(installers) != 1 or set(files) != {installers[0], Path(str(installers[0]) + '.sha256'),
                                              artifact_dir / BOOTSTRAP}:
        raise ValueError('artifact-must-have-one-setup-its-sha256-and-the-first-install-program')
    setup = installers[0]
    version = SOURCE.fullmatch(setup.name).group(1)
    checksum = Path(str(setup) + '.sha256').read_text(encoding='ascii').strip()
    exact = re.fullmatch(r'([a-fA-F0-9]{64})\s{2}([^\r\n]+)', checksum)
    if not exact or exact.group(2) != setup.name:
        raise ValueError('invalid-setup-sha256-sidecar')
    expected = exact.group(1).lower()
    if digest(setup) != expected:
        raise ValueError('setup-sha256-mismatch')
    verify_pe(setup, minimum_bytes)
    verify_pe(artifact_dir / BOOTSTRAP, min(minimum_bytes, BOOTSTRAP_MINIMUM))
    return setup, version, expected


def stage_release(artifact_dir: Path, output: Path, *, head_sha: str, run_id: int, run_number: int,
                  minimum_bytes: int = 1_000_000) -> dict:
    """Write the Release files into an empty output folder and describe the Release."""
    if not FULL_SHA.fullmatch(head_sha) or run_id < 1 or not 1 <= run_number <= 65535:
        raise ValueError('invalid-workflow-identity')
    setup, version, expected = original_setup(artifact_dir, minimum_bytes=minimum_bytes)
    if version.split('.')[2] != str(run_number):
        raise ValueError('version-build-mismatch')
    if output.exists() and (output.is_symlink() or not output.is_dir() or any(output.iterdir())):
        raise ValueError('output-must-be-empty')
    output.mkdir(parents=True, exist_ok=True)
    name = asset_name(version)
    target = output / name
    shutil.copyfile(setup, target)
    if digest(target) != expected:
        target.unlink(missing_ok=True)
        raise ValueError('copied-setup-sha256-mismatch')
    (output / (name + '.sha256')).write_text(f'{expected}  {name}\n', encoding='ascii')
    manifest = {'versao': version, 'arquivo': name, 'sha256': expected, 'tamanho': target.stat().st_size}
    (output / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    shutil.copyfile(artifact_dir / BOOTSTRAP, output / BOOTSTRAP)
    return {'tag': f'v{version}', 'versao': version, 'arquivos': [name, name + '.sha256', MANIFEST, BOOTSTRAP],
            'titulo': f'Coletor {version}',
            'notas': f'Instalador testado no Windows pela execução {run_id} (commit {head_sha}).\n\n'
                     f'SHA-256: `{expected}`'}


def changed_paths(text: str | None):
    return None if text is None else [line.strip() for line in text.splitlines() if line.strip()]


def main() -> None:
    if sys.argv[1:2] == ['decide']:
        decide = argparse.ArgumentParser(description='Decide whether this run publishes a Release')
        decide.add_argument('command')
        decide.add_argument('--newer-head-changes', type=Path, required=True)
        decide.add_argument('--since-release-changes', type=Path)
        options = decide.parse_args()
        since = options.since_release_changes
        print(publish_decision(
            newer_head_changes=changed_paths(options.newer_head_changes.read_text(encoding='utf-8')),
            since_release_changes=changed_paths(since.read_text(encoding='utf-8')) if since else None))
        return
    args = argparse.ArgumentParser(description='Stage a successful Windows-installer build as Release files')
    args.add_argument('--artifact-dir', type=Path, required=True)
    args.add_argument('--output', type=Path, required=True)
    args.add_argument('--head-sha', required=True)
    args.add_argument('--run-id', required=True, type=int)
    args.add_argument('--run-number', required=True, type=int)
    options = args.parse_args()
    result = stage_release(options.artifact_dir, options.output, head_sha=options.head_sha,
                           run_id=options.run_id, run_number=options.run_number)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
