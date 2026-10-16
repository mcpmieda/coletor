"""Publish a Windows-tested installer in /instalador, retaining five Git LFS builds.

This tool only *copies* an already validated CI artifact. It never runs the EXE,
contacts the internet or accesses real student records. The GitHub workflow owns
checking the upstream successful Windows run and pushing the atomic Git commit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import struct

SOURCE = re.compile(r"ColetorFrequencia-(\d+\.\d+\.\d+)-windows-x64-setup-candidato\.exe\Z")
STORED = re.compile(r"ColetorFrequencia-v\d+\.\d+\.\d+-build\d{6,12}-[0-9a-f]{12}-windows-x64-setup\.exe\Z")
FULL_SHA = re.compile(r"[0-9a-f]{40}\Z")
HEX_HASH = re.compile(r"[0-9a-f]{64}\Z")
KEEP = 5
MANIFEST = 'versoes.json'


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
    if len(installers) != 1 or set(files) != {installers[0], Path(str(installers[0]) + '.sha256')}:
        raise ValueError('artifact-must-have-one-setup-and-one-sha256')
    setup = installers[0]
    version = SOURCE.fullmatch(setup.name).group(1)
    checksum_file = Path(str(setup) + '.sha256')
    checksum = checksum_file.read_text(encoding='ascii').strip()
    exact = re.fullmatch(r'([a-fA-F0-9]{64})\s{2}([^\r\n]+)', checksum)
    if not exact or exact.group(2) != setup.name:
        raise ValueError('invalid-setup-sha256-sidecar')
    expected = exact.group(1).lower()
    if digest(setup) != expected:
        raise ValueError('setup-sha256-mismatch')
    verify_pe(setup, minimum_bytes)
    return setup, version, expected


def entry_ok(entry: object) -> bool:
    if not isinstance(entry, dict) or set(entry) != {
        'arquivo', 'sha256', 'versao', 'commit', 'run_id', 'run_number', 'publicado_em'
    }:
        return False
    name = entry['arquivo']
    return (
        isinstance(name, str) and STORED.fullmatch(name) is not None
        and isinstance(entry['sha256'], str) and HEX_HASH.fullmatch(entry['sha256']) is not None
        and isinstance(entry['versao'], str) and re.fullmatch(r'\d+\.\d+\.\d+', entry['versao']) is not None
        and isinstance(entry['commit'], str) and FULL_SHA.fullmatch(entry['commit']) is not None
        and type(entry['run_id']) is int and entry['run_id'] > 0
        and type(entry['run_number']) is int and entry['run_number'] > 0
        and isinstance(entry['publicado_em'], str) and len(entry['publicado_em']) <= 48
    )


def load_manifest(folder: Path) -> list[dict]:
    path = folder / MANIFEST
    if not path.exists():
        if any(folder.glob('*.exe')) or any(folder.glob('*.sha256')):
            raise ValueError('existing-installer-without-manifest')
        return []
    if path.is_symlink():
        raise ValueError('manifest-symlink-forbidden')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'formato', 'limite', 'versoes'} or data['formato'] != 1 or data['limite'] != KEEP:
        raise ValueError('bad-manifest-structure')
    entries = data['versoes']
    if not isinstance(entries, list) or len(entries) > KEEP or any(not entry_ok(e) for e in entries):
        raise ValueError('bad-manifest-entry')
    names = [e['arquivo'] for e in entries]
    if (len(names) != len(set(names)) or len({e['run_number'] for e in entries}) != len(entries)
            or names != [e['arquivo'] for e in sorted(entries, key=lambda e: e['run_number'], reverse=True)]):
        raise ValueError('unsorted-or-duplicated-manifest')
    existing_exes = {p.name for p in folder.glob('*.exe')}
    if existing_exes != set(names):
        raise ValueError('unmanaged-or-missing-installer')
    for e in entries:
        checksum_path = folder / (e['arquivo'] + '.sha256')
        if checksum_path.is_symlink() or not checksum_path.is_file():
            raise ValueError('missing-checksum')
        if checksum_path.read_text(encoding='ascii') != f"{e['sha256']}  {e['arquivo']}\n":
            raise ValueError('checksum-metadata-mismatch')
    if {p.name for p in folder.glob('*.sha256')} != {n + '.sha256' for n in names}:
        raise ValueError('unmanaged-checksum')
    return entries


def publish(repository: Path, artifact_dir: Path, *, head_sha: str, run_id: int,
            run_number: int, minimum_bytes: int = 1_000_000) -> dict:
    if not FULL_SHA.fullmatch(head_sha) or run_id < 1 or run_number < 1 or run_number > 999999999999:
        raise ValueError('invalid-workflow-identity')
    folder = repository / 'instalador'
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('installer-directory-missing')
    setup, version, expected = original_setup(artifact_dir, minimum_bytes=minimum_bytes)
    entries = load_manifest(folder)  # Validate before changing any file.
    filename = f'ColetorFrequencia-v{version}-build{run_number:06d}-{head_sha[:12]}-windows-x64-setup.exe'
    if not STORED.fullmatch(filename):
        raise ValueError('invalid-published-installer-name')
    previous = next((e for e in entries if e['arquivo'] == filename), None)
    if previous:
        if previous['commit'] != head_sha or previous['sha256'] != expected or previous['run_id'] != run_id:
            raise ValueError('published-build-metadata-conflict')
        return {'status': 'already-published', 'arquivo': filename, 'versoes': len(entries)}
    if any(e['run_number'] == run_number or e['commit'] == head_sha for e in entries):
        raise ValueError('duplicate-run-or-commit')
    current = {
        'arquivo': filename, 'sha256': expected, 'versao': version, 'commit': head_sha,
        'run_id': run_id, 'run_number': run_number,
        'publicado_em': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    selected = sorted([current, *entries], key=lambda e: e['run_number'], reverse=True)[:KEEP]
    # Older completed workflow runs cannot replace the latest five builds.
    if current not in selected:
        return {'status': 'obsolete', 'arquivo': filename, 'versoes': len(entries)}
    target = folder / filename
    if target.exists() or target.is_symlink():
        raise ValueError('target-already-exists')
    shutil.copyfile(setup, target)
    if digest(target) != expected:
        target.unlink(missing_ok=True)
        raise ValueError('copied-setup-sha256-mismatch')
    (folder / (filename + '.sha256')).write_text(f'{expected}  {filename}\n', encoding='ascii')
    retained = {e['arquivo'] for e in selected}
    for old in entries:
        if old['arquivo'] not in retained:
            (folder / old['arquivo']).unlink()
            (folder / (old['arquivo'] + '.sha256')).unlink()
    (folder / MANIFEST).write_text(
        json.dumps({'formato': 1, 'limite': KEEP, 'versoes': selected}, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    return {'status': 'published', 'arquivo': filename, 'versoes': len(selected), 'sha256': expected}


def main() -> None:
    args = argparse.ArgumentParser(description='Publish only successful Windows-installer Actions builds')
    args.add_argument('--repository', type=Path, default=Path('.'))
    args.add_argument('--artifact-dir', type=Path, required=True)
    args.add_argument('--head-sha', required=True)
    args.add_argument('--run-id', required=True, type=int)
    args.add_argument('--run-number', required=True, type=int)
    options = args.parse_args()
    result = publish(options.repository, options.artifact_dir, head_sha=options.head_sha,
                     run_id=options.run_id, run_number=options.run_number)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
