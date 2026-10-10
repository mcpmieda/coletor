import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

PATH = Path(__file__).resolve().parents[1] / "scripts/build_windows_portable.py"
spec = importlib.util.spec_from_file_location("portable_builder", PATH)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PortableBuildTests(unittest.TestCase):
    def test_runtime_url_and_hash_are_pinned(self):
        self.assertTrue(builder.PYTHON_URL.startswith("https://www.python.org/ftp/python/"))
        self.assertEqual(len(builder.PYTHON_SHA256), 64)
        self.assertIn("3.13.16", builder.PYTHON_URL)

    def test_archive_traversal_is_rejected(self):
        for name in ("../outside", "/absolute", "C:/drive", "folder\\escape"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                with ZipFile(root / "bad.zip", "w") as z:
                    z.writestr(name, "no")
                with self.assertRaises(ValueError):
                    builder.safe_extract(root / "bad.zip", root / "output")

    def test_ordinary_runtime_members_extract(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with ZipFile(root / "ok.zip", "w") as z:
                z.writestr("python313._pth", "python313.zip")
            builder.safe_extract(root / "ok.zip", root / "output")
            self.assertEqual((root / "output/python313._pth").read_text(), "python313.zip")

    def test_package_requires_native_smoke_success(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "failed.json").write_text('{"passed":false}')
            with self.assertRaises(ValueError):
                builder.package_zip(root, root / "failed.json")
