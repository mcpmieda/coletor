"""Pure synthetic regression tests for the five-version installer catalog."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from scripts.publish_windows_installer import publish


class PublishInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'instalador').mkdir()
        self.artifact = self.root / 'artifact'
        self.artifact.mkdir()

    def stage(self, version='0.4.0', *, valid_pe=True, correct_hash=True):
        for path in self.artifact.iterdir():
            path.unlink()
        name = f'ColetorFrequencia-{version}-windows-x64-setup-candidato.exe'
        exe = self.artifact / name
        raw = bytearray(1200)
        raw[:2] = b'MZ' if valid_pe else b'XX'
        struct.pack_into('<I', raw, 0x3c, 128)
        raw[128:132] = b'PE\0\0'
        exe.write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest() if correct_hash else '0' * 64
        (self.artifact / (name + '.sha256')).write_text(f'{sha}  {name}\n', encoding='ascii')

    def run_publish(self, i, **kwargs):
        return publish(self.root, self.artifact, head_sha=f'{i:040x}', run_id=39000000000+i,
                       run_number=i, minimum_bytes=100, **kwargs)

    def manifest(self):
        return json.loads((self.root/'instalador'/'versoes.json').read_text(encoding='utf-8'))['versoes']

    def test_instalador_folder_is_the_only_distribution_and_merges_itself(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/publish-installer.yml').read_text('utf8')
        checks = (Path(__file__).resolve().parents[1] / '.github/workflows/checks.yml').read_text('utf8')
        # Only instalador/ on main: no GitHub release, no chained workflow_run job.
        for text in ('gh release', 'archive-merge', 'gh workflow run checks.yml', "automation/instalador-*'"):
            self.assertNotIn(text, workflow)
        for text in ('gh pr create', '/approve', 'gh run watch', 'gh pr merge'):
            self.assertIn(text, workflow)
        self.assertNotIn('git push origin HEAD:main', workflow)
        self.assertNotIn('[skip ci]', workflow)
        self.assertIn("github.event_name != 'pull_request'", checks)
        self.assertIn('Installer archive-only merge', workflow)
        self.assertIn('Installer publisher maintenance only', workflow)
        self.assertIn('if ! pr_url="$(gh pr create', workflow)
        # Denied PR creation, missing checks or a blocked merge fail visibly.
        for code in ('ARCHIVE_PR_NOT_CREATED', 'ARCHIVE_CHECKS_NOT_STARTED', 'ARCHIVE_PR_NOT_MERGED'):
            self.assertIn(code, workflow)
        self.assertIn('exit 1\n          fi\n          echo "Created archive PR', workflow)
        self.assertIn('The installer is preserved in branch $branch', workflow)
        self.assertIn('all(.[]; .path | startswith(', workflow)

    def test_publishes_one_real_pe_and_same_sha256(self):
        self.stage()
        outcome = self.run_publish(1)
        self.assertEqual(outcome['status'], 'published')
        entry = self.manifest()[0]
        exe = self.root/'instalador'/entry['arquivo']
        self.assertTrue(exe.exists())
        self.assertEqual(hashlib.sha256(exe.read_bytes()).hexdigest(), entry['sha256'])
        self.assertEqual((self.root/'instalador'/(entry['arquivo']+'.sha256')).read_text('ascii'),
                         f"{entry['sha256']}  {entry['arquivo']}\n")

    def test_retains_only_five_visible_installers_and_hashes(self):
        for i in range(1, 8):
            self.stage(f'0.4.{i}')
            self.run_publish(i)
        entries = self.manifest()
        self.assertEqual([e['run_number'] for e in entries], [7,6,5,4,3])
        self.assertEqual(len(list((self.root/'instalador').glob('*.exe'))), 5)
        self.assertEqual(len(list((self.root/'instalador').glob('*.sha256'))), 5)
        self.assertEqual(sorted(p.name for p in (self.root/'instalador').glob('*.exe')),
                         [f'COLETOR v0.4.{i}.exe' for i in range(3, 8)])

    def test_retry_is_idempotent_and_old_run_cannot_replace_five(self):
        for i in range(1, 7):
            self.stage(f'0.4.{i}')
            self.run_publish(i)
        self.stage('0.4.6')
        self.assertEqual(self.run_publish(6)['status'], 'already-published')
        self.stage('0.4.1')
        self.assertEqual(self.run_publish(1)['status'], 'obsolete')
        self.assertEqual([e['run_number'] for e in self.manifest()], [6,5,4,3,2])

    def test_short_name_and_older_long_names_live_together(self):
        """"COLETOR v0.4.286.exe" from now on; the long names already kept rotate out (29/10/2026)."""
        folder = self.root/'instalador'
        raw = b'MZ' + bytes(98)
        sha = hashlib.sha256(raw).hexdigest()
        old = 'ColetorFrequencia-v0.4.1-build000001-' + 'a'*12 + '-windows-x64-setup.exe'
        (folder/old).write_bytes(raw)
        (folder/(old + '.sha256')).write_text(f'{sha}  {old}\n', encoding='ascii')
        (folder/'versoes.json').write_text(json.dumps({'formato': 1, 'limite': 5, 'versoes': [{
            'arquivo': old, 'sha256': sha, 'versao': '0.4.1', 'commit': 'a'*40, 'run_id': 1, 'run_number': 1,
            'publicado_em': '2026-10-28T12:00:00+00:00'}]}), encoding='utf-8')
        self.stage('0.4.2')
        self.assertEqual(self.run_publish(2)['arquivo'], 'COLETOR v0.4.2.exe')
        self.assertEqual([e['arquivo'] for e in self.manifest()], ['COLETOR v0.4.2.exe', old])

    def test_invalid_hash_is_rejected_without_modifying_previous_version(self):
        self.stage()
        self.run_publish(1)
        before = (self.root/'instalador'/'versoes.json').read_bytes()
        self.stage(correct_hash=False)
        with self.assertRaisesRegex(ValueError, 'sha256-mismatch'):
            self.run_publish(2)
        self.assertEqual((self.root/'instalador'/'versoes.json').read_bytes(), before)
        self.assertEqual(len(list((self.root/'instalador').glob('*.exe'))), 1)

    def test_fake_exe_is_rejected(self):
        self.stage(valid_pe=False)
        with self.assertRaisesRegex(ValueError, 'not-Windows-PE-MZ'):
            self.run_publish(1)
        self.assertFalse((self.root/'instalador'/'versoes.json').exists())

    def test_unmanaged_file_blocks_deletion(self):
        self.stage()
        self.run_publish(1)
        (self.root/'instalador'/'manual.exe').write_bytes(b'preserve')
        self.stage()
        with self.assertRaisesRegex(ValueError, 'unmanaged-or-missing-installer'):
            self.run_publish(2)
        self.assertEqual((self.root/'instalador'/'manual.exe').read_bytes(), b'preserve')

    def test_bad_checksum_sidecar_does_not_publish(self):
        self.stage()
        sidecar = next(self.artifact.glob('*.sha256'))
        sidecar.write_text('1'*64 + '  wrong.exe\n', encoding='ascii')
        with self.assertRaisesRegex(ValueError, 'invalid-setup-sha256-sidecar'):
            self.run_publish(1)

if __name__ == '__main__':
    unittest.main()
