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

    def test_protected_main_publishes_release_then_checked_archive_pr(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/publish-installer.yml').read_text('utf8')
        checks = (Path(__file__).resolve().parents[1] / '.github/workflows/checks.yml').read_text('utf8')
        for text in ('gh release create', 'gh release delete', 'gh pr create', 'gh workflow run checks.yml', 'gh pr merge'):
            self.assertIn(text, workflow)
        self.assertNotIn('git push origin HEAD:main', workflow)
        self.assertNotIn('[skip ci]', workflow)
        self.assertIn('workflow_dispatch:', checks)
        self.assertIn("github.event_name != 'pull_request'", checks)
        self.assertIn('Installer archive-only merge', workflow)
        self.assertIn('if ! pr_url="$(gh pr create', workflow)
        # Release publication can succeed while the archive remains stale.
        # Denied PR creation/merge must fail visibly instead of reporting green.
        self.assertIn('ARCHIVE_PR_NOT_CREATED', workflow)
        self.assertIn('ARCHIVE_PR_NOT_MERGED', workflow)
        self.assertIn('exit 1\\n          fi\\n          echo "Created archive PR', workflow)
        self.assertIn('The installer is preserved in branch $branch', workflow)
        self.assertNotIn('Actions cannot open archive PR.', workflow)
        self.assertIn("github.event.workflow_run.event == 'workflow_dispatch'", workflow)
        self.assertIn("startsWith(github.event.workflow_run.head_branch, 'automation/instalador-run-')", workflow)
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
            self.stage()
            self.run_publish(i)
        entries = self.manifest()
        self.assertEqual([e['run_number'] for e in entries], [7,6,5,4,3])
        self.assertEqual(len(list((self.root/'instalador').glob('*.exe'))), 5)
        self.assertEqual(len(list((self.root/'instalador').glob('*.sha256'))), 5)
        self.assertFalse(any('build000001-' in p.name for p in (self.root/'instalador').glob('*.exe')))

    def test_retry_is_idempotent_and_old_run_cannot_replace_five(self):
        for i in range(1, 7):
            self.stage()
            self.run_publish(i)
        self.stage()
        self.assertEqual(self.run_publish(6)['status'], 'already-published')
        self.assertEqual(self.run_publish(1)['status'], 'obsolete')
        self.assertEqual([e['run_number'] for e in self.manifest()], [6,5,4,3,2])

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
