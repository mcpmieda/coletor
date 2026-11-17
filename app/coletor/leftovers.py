"""Files an earlier version left in the installed program folder.

The installer copies the new version over the old one, so what a version stops shipping stays:
every interface build left its own bundle behind (17 files, 28 MB, on a computer updated since
October 2026), and a module or package file removed from the program could still be imported.
Once the new version runs, what programa/ holds beyond the package's own inventory is deleted.
Nothing goes before the new files are in place, so an installation cut short still leaves a
Coletor that opens. The inventory is MANIFEST.json, which the installation test compares with the
installed folder in both directions (scripts/check_windows_installer.py).
"""
import json
import os
from pathlib import Path

PROGRAM = 'programa'
MANIFEST = 'MANIFEST.json'


def leftovers(folder, version, own=__file__):
    """The files programa/ holds beyond the inventory of the installed version.

    None unless the inventory is this version's and lists this very module: one of another
    version, or whose paths do not meet the running program, proves nothing about the folder."""
    try:
        folder = Path(folder).resolve()
        manifest = json.loads((folder / MANIFEST).read_text(encoding='utf-8'))
    except (OSError, ValueError): return []
    if not isinstance(manifest, dict) or manifest.get('product_version') != version: return []
    files = manifest.get('files')
    if not isinstance(files, list): return []
    listed = {os.path.normcase(os.path.normpath(item['path'])) for item in files
              if isinstance(item, dict) and isinstance(item.get('path'), str)}

    def known(path):
        return os.path.normcase(os.path.relpath(path, folder)) in listed

    try: inside = known(Path(own).resolve())
    except (OSError, ValueError): return []
    if not inside: return []
    found = []
    for base, _, names in os.walk(folder / PROGRAM):  # Never through a link or junction.
        for name in names:
            path = Path(base, name)
            # Bytecode of a module that is still part of the program (written by the interpreter, or
            # packed with it) stays.
            if not known(path) and not (path.parent.name == '__pycache__'
                                        and known(path.parent.parent / (name.split('.')[0] + '.py'))):
                found.append(path)
    return found


def remove_leftovers(folder, version, own=__file__):
    """Delete what leftovers() finds; how many files went."""
    removed, emptied, program = 0, set(), Path(folder).resolve() / PROGRAM
    for path in leftovers(folder, version, own):
        try: path.unlink()
        except OSError: continue
        removed += 1
        emptied.add(path.parent)
    # Only folders this cleanup emptied: one the package ships empty stays.
    for path in sorted(emptied, key=lambda p: len(p.parts), reverse=True):
        while path != program:
            try: path.rmdir()
            except OSError: break
            path = path.parent
    return removed
