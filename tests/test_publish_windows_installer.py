"""Synthetic tests: a tested installer becomes the files of one GitHub Release (15/11/2026)."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from scripts.publish_windows_installer import BOOTSTRAP, publish_decision, stage_release

ROOT = Path(__file__).resolve().parents[1]


class PublishInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.artifact = self.root / 'artifact'
        self.artifact.mkdir()
        self.output = self.root / 'release'

    def stage(self, version='0.4.7', *, valid_pe=True, correct_hash=True):
        for path in self.artifact.iterdir():
            path.unlink()
        name = f'ColetorFrequencia-{version}-windows-x64-setup-candidato.exe'
        raw = bytearray(1200)
        raw[:2] = b'MZ' if valid_pe else b'XX'
        struct.pack_into('<I', raw, 0x3c, 128)
        raw[128:132] = b'PE\0\0'
        (self.artifact / name).write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest() if correct_hash else '0' * 64
        (self.artifact / (name + '.sha256')).write_text(f'{sha}  {name}\n', encoding='ascii')
        (self.artifact / BOOTSTRAP).write_bytes(raw[:200])  # "Instalar Coletor.exe" of the same build.
        return bytes(raw)

    def run_stage(self, number=7):
        return stage_release(self.artifact, self.output, head_sha=f'{number:040x}', run_id=39000000000 + number,
                             run_number=number, minimum_bytes=100)

    def test_release_has_installer_checksum_and_update_manifest(self):
        raw = self.stage()
        result = self.run_stage()
        self.assertEqual(result['tag'], 'v0.4.7')
        self.assertEqual(result['arquivos'], ['COLETOR-v0.4.7.exe', 'COLETOR-v0.4.7.exe.sha256', 'atualizacao.json',
                                              'Instalar-Coletor.exe'])
        self.assertEqual(sorted(p.name for p in self.output.iterdir()), sorted(result['arquivos']))
        self.assertEqual((self.output / 'Instalar-Coletor.exe').read_bytes(), raw[:200])
        sha = hashlib.sha256(raw).hexdigest()
        self.assertEqual((self.output / 'COLETOR-v0.4.7.exe').read_bytes(), raw)
        self.assertEqual((self.output / 'COLETOR-v0.4.7.exe.sha256').read_text('ascii'), f'{sha}  COLETOR-v0.4.7.exe\n')
        manifest = json.loads((self.output / 'atualizacao.json').read_text('utf-8'))
        self.assertEqual(manifest, {'versao': '0.4.7', 'arquivo': 'COLETOR-v0.4.7.exe', 'sha256': sha, 'tamanho': len(raw)})

    def test_manifest_is_what_the_updater_accepts(self):
        from coletor.updater import read_manifest
        self.stage()
        self.run_stage()
        manifest = (self.output / 'atualizacao.json').read_bytes()
        with self.assertRaisesRegex(Exception, 'bad-manifest'):
            read_manifest(manifest)  # 1200 bytes is below the real minimum; the format itself is checked next.
        value = json.loads(manifest)
        value['tamanho'] = 40_000_000
        self.assertEqual(read_manifest(json.dumps(value).encode())['arquivo'], 'COLETOR-v0.4.7.exe')

    def test_version_must_be_this_run(self):
        self.stage('0.4.6')
        with self.assertRaisesRegex(ValueError, 'version-build-mismatch'):
            self.run_stage(7)
        self.assertFalse(self.output.exists())

    def test_invalid_hash_fake_exe_and_bad_sidecar_publish_nothing(self):
        self.stage(correct_hash=False)
        with self.assertRaisesRegex(ValueError, 'sha256-mismatch'):
            self.run_stage()
        self.stage(valid_pe=False)
        with self.assertRaisesRegex(ValueError, 'not-Windows-PE-MZ'):
            self.run_stage()
        self.stage()
        sidecar = next(self.artifact.glob('*.sha256'))
        sidecar.write_text('1' * 64 + '  wrong.exe\n', encoding='ascii')
        with self.assertRaisesRegex(ValueError, 'invalid-setup-sha256-sidecar'):
            self.run_stage()
        # A build without "Instalar Coletor.exe", or with something that is not a program in its place.
        self.stage()
        (self.artifact / BOOTSTRAP).unlink()
        with self.assertRaisesRegex(ValueError, 'first-install-program'):
            self.run_stage()
        self.stage()
        (self.artifact / BOOTSTRAP).write_bytes(b'x' * 200)
        with self.assertRaisesRegex(ValueError, 'not-Windows-PE-MZ'):
            self.run_stage()
        self.assertFalse(self.output.exists())

    def test_output_must_start_empty(self):
        self.stage()
        self.output.mkdir()
        (self.output / 'other.txt').write_text('x', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'output-must-be-empty'):
            self.run_stage()

    def test_only_a_program_change_becomes_a_release(self):
        decide = publish_decision
        # First Release; then nothing new in the program; then a docs-only commit after an app change.
        self.assertEqual(decide(newer_head_changes=[], since_release_changes=None), 'publish')
        self.assertEqual(decide(newer_head_changes=[], since_release_changes=['docs/X.md', 'tests/test_x.py',
                                                                              '.github/workflows/checks.yml']),
                         'program-unchanged')
        for path in ('app/coletor/updater.py', 'ui/src/App.tsx', 'installer/Coletor.iss',
                     'scripts/build_windows_portable.py', 'requirements-windows-portable.txt',
                     'docs/PORTABLE_LEIA_ME.txt', 'scripts/bootstrap/InstalarColetor.cs'):
            self.assertEqual(decide(newer_head_changes=[], since_release_changes=['README.md', path]), 'publish')
        # A newer commit already on main: its own run publishes if it changes the program...
        self.assertEqual(decide(newer_head_changes=['app/coletor/desktop.py'], since_release_changes=['app/x.py']),
                         'newer-build-follows')
        # ...and if it only changes docs, this run's program is not lost.
        self.assertEqual(decide(newer_head_changes=['docs/WINDOWS_INSTALLER.md'], since_release_changes=['app/x.py']),
                         'publish')

    def test_the_first_install_program_is_built_by_the_ci_and_reads_what_the_updater_reads(self):
        """Owner request 16/11/2026: "Instalar Coletor.exe" downloads the newest Release. Since 17/11/2026 it
        is built, signed and published by the CI with every Release, never compiled by hand. The copy in
        instalador/ (owner request 17/11/2026: easy to find) is one of those published files; the Windows
        CI refuses it without the school's signature (scripts/check_windows_signature.py)."""
        tracked = __import__('subprocess').run(['git', 'ls-files', '-z', '*.exe'], cwd=ROOT, capture_output=True,
                                               text=True, check=True).stdout.split('\0')
        self.assertEqual([path for path in tracked if path], ['instalador/Instalar Coletor.exe'])
        self.assertEqual((ROOT / 'instalador/Instalar Coletor.exe').read_bytes()[:2], b'MZ')
        self.assertEqual(publish_decision(newer_head_changes=[], since_release_changes=['instalador/Instalar Coletor.exe']),
                         'program-unchanged')  # Refreshing the copy makes no computer reinstall.
        source = (ROOT / 'scripts/bootstrap/InstalarColetor.cs').read_text(encoding='utf-8')
        from coletor import updater
        self.assertIn(f'const string Publisher = "{updater.PUBLISHER}"', source)
        self.assertIn(f'const string Manifest = "{updater.MANIFEST_NAME}"', source)
        self.assertIn('"COLETOR-v" + version + ".exe"', source)
        self.assertIn(f'"https://api.github.com/repos/{updater.REPOSITORY}/releases/latest"', source)
        checks = (ROOT / '.github/workflows/checks.yml').read_text('utf8')
        self.assertIn(f"$First = 'dist/windows-installer/{BOOTSTRAP}'", checks)
        self.assertIn('scripts/check_windows_signature.py', checks)
        self.assertIn("--repository-copy 'instalador/Instalar Coletor.exe'", checks)

    def test_workflow_publishes_releases_not_repository_files(self):
        workflow = (ROOT / '.github/workflows/publish-installer.yml').read_text('utf8')
        for text in ('gh release create', '--latest', '--cleanup-tag', 'tail -n +6', 'sort -V'):
            self.assertIn(text, workflow)
        for text in ('git push', 'gh pr create', 'gh pr merge', 'git lfs', 'pull-requests: write'):
            self.assertNotIn(text, workflow)
        self.assertIn('publish_windows_installer.py decide', workflow)
        self.assertIn('isDraft', workflow)
        # 15/11/2026: on 404 gh printed the error body on stdout and it was taken as the latest tag.
        self.assertIn("latest='' # gh prints the 404 body on stdout", workflow)
        self.assertIn('Unexpected latest Release tag', workflow)
        self.assertIn('fetch-depth: 0', workflow)
        self.assertNotIn('filter=lfs', (ROOT / '.gitattributes').read_text('utf8'))


if __name__ == '__main__':
    unittest.main()
