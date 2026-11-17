"""What an earlier version left in the installed program folder (synthetic files only)."""
import json
from pathlib import Path
import tempfile
import unittest

from coletor.leftovers import remove_leftovers

SHIPPED = ['Abrir Coletor.cmd', 'programa/ColetorFrequencia.exe', 'programa/app/coletor/leftovers.py',
           'programa/app/coletor/parser.py', 'programa/ui/dist/index.html', 'programa/ui/dist/assets/index-new.js']
# Left by earlier versions: an interface bundle, a module no longer shipped, its bytecode, a package's folder.
LEFT = ['programa/ui/dist/assets/index-old.js', 'programa/app/coletor/removed.py',
        'programa/app/coletor/__pycache__/removed.cpython-313.pyc', 'programa/site-packages/old-1.0.dist-info/METADATA']
# Not the program's: the uninstaller, the installer's text, and bytecode of a module still shipped.
KEPT = ['unins000.exe', 'INSTALACAO-E-RETIRADA.txt', 'programa/app/coletor/__pycache__/parser.cpython-313.pyc']


class LeftoversTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        for name in SHIPPED + LEFT + KEPT:
            (self.folder / name).parent.mkdir(parents=True, exist_ok=True)
            (self.folder / name).write_text('x', encoding='utf-8')
        (self.folder / 'programa/vazia').mkdir()  # A folder the package ships empty.
        self.own = self.folder / 'programa/app/coletor/leftovers.py'
        self.inventory('0.4.400', SHIPPED)

    def inventory(self, version, paths):
        (self.folder / 'MANIFEST.json').write_text(json.dumps(
            {'product_version': version, 'files': [{'path': path, 'size': 1, 'sha256': '0' * 64} for path in paths]}), encoding='utf-8')

    def present(self):
        return sorted(p.relative_to(self.folder).as_posix() for p in self.folder.rglob('*') if p.is_file() and p.name != 'MANIFEST.json')

    def test_only_what_the_inventory_does_not_list_goes(self):
        self.assertEqual(remove_leftovers(self.folder, '0.4.400', self.own), len(LEFT))
        self.assertEqual(self.present(), sorted(SHIPPED + KEPT))
        # A folder emptied here goes with its files; one shipped empty stays.
        self.assertFalse((self.folder / 'programa/site-packages').exists())
        self.assertTrue((self.folder / 'programa/vazia').is_dir())
        self.assertEqual(remove_leftovers(self.folder, '0.4.400', self.own), 0)

    def test_an_inventory_that_proves_nothing_deletes_nothing(self):
        everything = sorted(SHIPPED + LEFT + KEPT)
        self.assertEqual(remove_leftovers(self.folder, '0.4.399', self.own), 0)  # Another version's.
        self.assertEqual(remove_leftovers(self.folder, '0.4.400', __file__), 0)  # Not this program's folder.
        self.inventory('0.4.400', [p for p in SHIPPED if not p.endswith('leftovers.py')])
        self.assertEqual(remove_leftovers(self.folder, '0.4.400', self.own), 0)  # Does not list the running module.
        for text in ('', '[]', '{"product_version": "0.4.400", "files": "all"}'):
            (self.folder / 'MANIFEST.json').write_text(text, encoding='utf-8')
            self.assertEqual(remove_leftovers(self.folder, '0.4.400', self.own), 0)
        (self.folder / 'MANIFEST.json').unlink()
        self.assertEqual(remove_leftovers(self.folder, '0.4.400', self.own), 0)
        self.assertEqual(self.present(), everything)

    def test_the_installed_coletor_is_cleaned_by_its_own_inventory(self):
        # The real folder's shape: Windows paths in any case, the inventory in the package's.
        self.inventory('0.4.400', [p.upper() if p.endswith('.html') else p for p in SHIPPED])
        self.assertEqual(remove_leftovers(str(self.folder), '0.4.400', str(self.own)), len(LEFT))
        self.assertEqual(self.present(), sorted(SHIPPED + KEPT))


if __name__ == '__main__':
    unittest.main()
