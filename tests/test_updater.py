"""Automatic update from GitHub Releases: only newer, verified installers, only at a safe moment."""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from coletor import updater  # noqa: E402
from coletor.frequency_runtime import FrequencyRuntime  # noqa: E402

SCRIPT = (ROOT / "installer/Coletor.iss").read_text(encoding="utf-8-sig")
SCHOOL = next(iter(updater.SIGNERS))


def setup_bytes(size=1_200_000):
    raw = bytearray(size)
    raw[:2] = b'MZ'
    struct.pack_into('<I', raw, 0x3c, 128)
    raw[128:132] = b'PE\0\0'
    return bytes(raw)


def manifest_for(version, raw):
    return {'versao': version, 'arquivo': f'COLETOR-v{version}.exe',
            'sha256': hashlib.sha256(raw).hexdigest(), 'tamanho': len(raw)}


def release_for(manifest, author=updater.PUBLISHER, uploader=updater.PUBLISHER, draft=False):
    asset = lambda name, size: {'name': name, 'state': 'uploaded', 'size': size, 'uploader': {'login': uploader}}
    return {'tag_name': f"v{manifest['versao']}", 'draft': draft, 'author': {'login': author},
            'assets': [asset(manifest['arquivo'], manifest['tamanho']), asset(manifest['arquivo'] + '.sha256', 90),
                       asset(updater.MANIFEST_NAME, 150)]}


class PublisherTests(unittest.TestCase):
    def test_only_releases_made_and_uploaded_by_the_publishing_workflow(self):
        manifest = manifest_for('0.4.330', setup_bytes())
        check = lambda release: updater.check_publisher(json.dumps(release).encode(), manifest)
        check(release_for(manifest))
        for release, code in ((release_for(manifest, author='someone'), 'untrusted-release'),
                              (release_for(manifest, uploader='coderabbitai[bot]'), 'untrusted-release'),
                              (release_for(manifest, draft=True), 'bad-release'),
                              ({**release_for(manifest), 'tag_name': 'v0.4.331'}, 'bad-release')):
            with self.subTest(code=code), self.assertRaisesRegex(updater.UpdateError, code):
                check(release)
        replaced = release_for(manifest)
        replaced['assets'][0]['size'] += 1
        with self.assertRaisesRegex(updater.UpdateError, 'bad-release'):
            check(replaced)
        missing = release_for(manifest)
        missing['assets'] = missing['assets'][:2]
        with self.assertRaisesRegex(updater.UpdateError, 'bad-release'):
            check(missing)
        self.assertIn('api.github.com', updater.ALLOWED_HOSTS)


class Response:
    def __init__(self, status, body=b'', location=None):
        self.status, self._body, self._location = status, body, location

    def getheader(self, name):
        return self._location if name == 'Location' else None

    def read(self, size=-1):
        if size < 0: size = len(self._body)
        part, self._body = self._body[:size], self._body[size:]
        return part


class Connection:
    def __init__(self, routes, host, log):
        self.routes, self.host, self.log = routes, host, log

    def request(self, method, path, headers=None):
        self.log.append((self.host, path))
        self.path = path

    def getresponse(self):
        return self.routes[(self.host, self.path)]()

    def close(self):
        pass


def connector(routes, log):
    return lambda host: Connection(routes, host, log)


class ManifestTests(unittest.TestCase):
    def test_accepts_only_the_exact_format(self):
        raw = setup_bytes()
        good = manifest_for('0.4.330', raw)
        self.assertEqual(updater.read_manifest(json.dumps(good).encode()), good)
        for change in ({'arquivo': 'outro.exe'}, {'versao': '0.4'}, {'sha256': 'A' * 64}, {'tamanho': 10},
                       {'tamanho': updater.SETUP_LIMIT + 1}, {'tamanho': '1200000'}, {'extra': 1}):
            with self.subTest(change=change), self.assertRaises(updater.UpdateError):
                updater.read_manifest(json.dumps({**good, **change}).encode())
        with self.assertRaises(updater.UpdateError):
            updater.read_manifest(b'\xff')

    def test_versions_compare_as_numbers(self):
        self.assertGreater(updater.parse_version('0.4.330'), updater.parse_version('0.4.99'))
        with self.assertRaises(updater.UpdateError):
            updater.parse_version('0.4.330-teste')


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / 'atualizacao'
        self.log = []

    def routes(self, raw, version='0.4.330', location='https://release-assets.githubusercontent.com/x?sig=1'):
        path = f'/mcpmieda/coletor/releases/download/v{version}/COLETOR-v{version}.exe'
        return {('github.com', path): lambda: Response(302, location=location),
                ('release-assets.githubusercontent.com', '/x?sig=1'): lambda: Response(200, raw)}

    def test_follows_github_redirect_and_verifies_the_file(self):
        raw = setup_bytes()
        target = updater.download_setup(manifest_for('0.4.330', raw), self.folder, connector(self.routes(raw), self.log))
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(target.name, 'COLETOR-v0.4.330.exe')
        self.assertEqual([host for host, _ in self.log], ['github.com', 'release-assets.githubusercontent.com'])
        # Already downloaded and still valid: no second download.
        updater.download_setup(manifest_for('0.4.330', raw), self.folder, connector({}, self.log))
        self.assertEqual(len(self.log), 2)

    def test_redirect_to_another_host_is_refused(self):
        raw = setup_bytes()
        routes = self.routes(raw, location='https://example.com/x')
        with self.assertRaisesRegex(updater.UpdateError, 'host-not-allowed'):
            updater.download_setup(manifest_for('0.4.330', raw), self.folder, connector(routes, self.log))
        routes = self.routes(raw, location='http://release-assets.githubusercontent.com/x?sig=1')
        with self.assertRaisesRegex(updater.UpdateError, 'host-not-allowed'):
            updater.download_setup(manifest_for('0.4.330', raw), self.folder, connector(routes, self.log))

    def test_wrong_bytes_or_size_leave_nothing_behind(self):
        raw = setup_bytes()
        other = raw[:-1] + b'\1'
        with self.assertRaisesRegex(updater.UpdateError, 'checksum-mismatch'):
            updater.download_setup(manifest_for('0.4.330', raw), self.folder, connector(self.routes(other), self.log))
        bigger = raw + b'\0'
        with self.assertRaisesRegex(updater.UpdateError, 'size-mismatch'):
            updater.download_setup(manifest_for('0.4.330', raw), self.folder, connector(self.routes(bigger), self.log))
        not_pe = b'XX' + raw[2:]
        with self.assertRaisesRegex(updater.UpdateError, 'checksum-mismatch'):
            updater.download_setup(manifest_for('0.4.330', not_pe), self.folder, connector(self.routes(not_pe), self.log))
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_manifest_size_is_limited(self):
        routes = {('github.com', '/m'): lambda: Response(200, b'x' * (updater.MANIFEST_LIMIT + 1))}
        with self.assertRaisesRegex(updater.UpdateError, 'too-large'):
            updater.fetch_small('https://github.com/m', connect=connector(routes, self.log))


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.install = base / 'Programs/ColetorFrequenciaSmecel'
        (self.install / 'programa').mkdir(parents=True)
        (self.install / 'unins000.exe').write_bytes(b'x')
        self.settings = base / 'settings'
        self.raw = setup_bytes()
        self.launched = []

    def make(self, current='0.4.329', latest='0.4.330', *, safe=lambda: True, power=lambda: True,
             space=lambda folder, size: True, clock=lambda: 1_000_000, signer=lambda path: SCHOOL, idle=None):
        def download(manifest, folder):
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / manifest['arquivo']
            path.write_bytes(self.raw)
            return path
        return updater.Updater(current, self.install / 'programa', self.settings, safe_now=safe, idle_now=idle,
                               launch=self.launched.append, download=download, power=power, space=space,
                               clock=clock, clear_resume=lambda: None, signer=signer,
                               fetch=lambda url, limit=None: json.dumps(
                                   release_for(manifest_for(latest, self.raw)) if 'api.github.com' in url
                                   else manifest_for(latest, self.raw)).encode())

    def test_only_an_installed_ci_build_updates_itself(self):
        self.assertTrue(self.make().enabled())
        self.assertFalse(self.make(current='0.4.0').enabled())  # Development copy.
        (self.install / 'unins000.exe').unlink()
        self.assertFalse(self.make().enabled())  # Portable folder.

    def test_newer_version_is_installed(self):
        self.assertTrue(self.make().check_once())
        self.assertEqual([p.name for p in self.launched], ['COLETOR-v0.4.330.exe'])

    def test_an_installer_the_school_did_not_sign_is_never_run(self):
        # A Release can be written as github-actions[bot] by a workflow of any branch; only main signs.
        for who in (None, 'f' * 64):  # No intact signature; someone else's certificate.
            item = self.make(signer=lambda path, who=who: who)
            with self.assertRaisesRegex(updater.UpdateError, 'untrusted-signature'):
                item.check_once()
            self.assertEqual(self.launched, [])
            self.assertEqual(list((self.settings / 'atualizacao').glob('*.exe')), [])  # Not kept for a later try.

    def test_the_installer_and_the_first_install_accept_the_same_certificates(self):
        source = (ROOT / 'scripts/bootstrap/InstalarColetor.cs').read_text(encoding='utf-8')
        listed = re.search(r'Signers = \{([^}]*)\}', source).group(1)
        self.assertEqual(set(re.findall(r'"([0-9a-f]{64})"', listed)), set(updater.SIGNERS))
        self.assertTrue(all(updater.HEX_HASH.fullmatch(item) for item in updater.SIGNERS))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows Authenticode')
    def test_a_file_with_no_signature_has_no_signer(self):
        # Signed and changed files are checked with real certificates by scripts/check_windows_signature.py.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'setup.exe'
            path.write_bytes(setup_bytes())
            self.assertIsNone(updater.signer(path))
            self.assertIsNone(updater.signer(Path(folder) / 'missing.exe'))
        self.assertNotIn(updater.signer(sys.executable), updater.SIGNERS)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows Authenticode')
    def test_the_copy_in_the_instalador_folder_is_one_the_school_signed(self):
        self.assertIn(updater.signer(ROOT / 'instalador' / 'Instalar Coletor.exe'), updater.SIGNERS)

    def test_same_or_older_version_does_nothing_and_cleans_old_downloads(self):
        folder = self.settings / 'atualizacao'
        folder.mkdir(parents=True)
        (folder / 'COLETOR-v0.4.329.exe').write_bytes(b'old')
        (folder / 'COLETOR-v0.4.329.exe.part').write_bytes(b'old')
        self.assertFalse(self.make(latest='0.4.329').check_once())
        self.assertFalse(self.make(current='0.4.331').check_once())
        self.assertEqual(self.launched, [])
        self.assertEqual(list(folder.iterdir()), [])

    def test_no_disk_space_downloads_nothing(self):
        with self.assertRaisesRegex(updater.UpdateError, 'disk-full'):
            self.make(space=lambda folder, size: False).check_once()
        self.assertEqual(self.launched, [])

    def test_waits_for_a_safe_moment_and_enough_battery(self):
        answers = iter([False, True, True])
        power = iter([False, True])
        item = self.make(safe=lambda: next(answers), power=lambda: next(power))
        waits = []
        item._pause = lambda seconds: waits.append(seconds) or False
        self.assertTrue(item.check_once())
        self.assertEqual(waits, [updater.SAFE_RETRY_SECONDS, updater.SAFE_RETRY_SECONDS])
        self.assertEqual(len(self.launched), 1)

    def test_a_check_asked_for_in_ajustes_says_what_the_latest_version_is(self):
        self.assertEqual(self.make().check_now(), {'state': 'unavailable'})  # The updater never started here.
        current = self.make(latest='0.4.329')
        current._thread = object()
        self.assertEqual(current.check_now(), {'state': 'current', 'version': '0.4.329'})
        self.assertFalse(current._asked)
        item = self.make()
        item._thread = object()
        self.assertEqual(item.check_now(), {'state': 'found', 'version': '0.4.330'})
        self.assertTrue(item._wake.is_set())  # The updater's own thread does the rest, now.
        self.assertEqual(self.launched, [])

    def test_an_update_asked_for_waits_only_for_the_collection_in_progress(self):
        # The agenda is never quiet (a time every 15 minutes, 07:00 to 17:40): nobody asked, it waits.
        running = iter([False, True])  # A collection in progress, then over.
        item = self.make(safe=lambda: False, idle=lambda: next(running))
        item._thread = object()
        item.check_now()
        waits = []
        item._pause = lambda seconds: waits.append(seconds) or False
        self.assertTrue(item.check_once())
        self.assertEqual((waits, len(self.launched), item._asked), ([updater.SAFE_RETRY_SECONDS], 1, False))
        # The next one, that nobody asked for, waits for the agenda again.
        waits.clear()
        item._pause = lambda seconds: waits.append(seconds) or True
        item._attempts.clear()
        self.assertFalse(item.check_once())
        self.assertEqual((waits, len(self.launched)), ([updater.SAFE_RETRY_SECONDS], 1))

    def test_an_update_asked_for_tries_again_a_version_that_failed_today(self):
        item = self.make()
        self.assertTrue(item.check_once())
        with self.assertRaisesRegex(updater.UpdateError, 'waiting-after-failed-install'):
            item.check_once()
        item._thread = object()
        item.check_now()
        self.assertTrue(item.check_once())
        self.assertEqual(len(self.launched), 2)

    def test_stop_while_waiting_never_launches(self):
        item = self.make(safe=lambda: False)
        item.stop()
        self.assertFalse(item.check_once())
        self.assertEqual(self.launched, [])

    def test_resume_command_and_installer_agree(self):
        folder = Path(r'C:\Users\Nome Sobrenome\AppData\Local\ColetorFrequenciaSmecel\atualizacao')
        command = updater.resume_command(folder / 'COLETOR-v0.4.330.exe', folder / updater.INSTALL_LOG)
        self.assertTrue(command.startswith('"C:\\Users\\Nome Sobrenome\\'))
        for argument in (*updater.SETUP_ARGUMENTS, updater.RESUME_ARGUMENT):
            self.assertIn(argument, command)
        self.assertIn('"/LOG=C:\\Users\\Nome Sobrenome\\', command)
        self.assertIn(f"SetupMutex={updater.INSTALLER_MUTEX}", SCRIPT)
        self.assertEqual(re.search(r"^\s*ResumeValue = '(.+)';", SCRIPT, re.M).group(1), updater.RESUME_VALUE)
        self.assertIn(updater.RUN_ONCE_KEY, SCRIPT)
        self.assertEqual(updater.RESUME_ARGUMENT, '/REABRIR=1')
        self.assertIn("{param:REABRIR|0}", SCRIPT)
        post = SCRIPT.split("procedure CurStepChanged", 1)[1]
        self.assertIn("RegDeleteValue(HKCU, RunOnceKey, ResumeValue);", post.split("procedure CurUninstallStepChanged")[0])
        self.assertIn("RegDeleteValue(HKCU, RunOnceKey, ResumeValue);", post.split("procedure CurUninstallStepChanged")[1])
        # A failed installation reopens the Coletor it closed and drops the sign-in resume.
        failed = SCRIPT.split("procedure DeinitializeSetup", 1)[1].split("end;\n\n", 1)[0]
        self.assertIn("if Installed or IsUninstaller then exit;", failed)
        self.assertIn("RegDeleteValue(HKCU, RunOnceKey, ResumeValue);", failed)
        self.assertIn("ReopenCollector();", failed)
        # The sign-in start waits while the resumed installer replaces the folder.
        launcher = (ROOT / "installer/launcher/ColetorFrequencia.cs").read_text(encoding="utf-8")
        self.assertIn(f'ResumeValue = "{updater.RESUME_VALUE}"', launcher)
        self.assertIn('@"' + updater.RUN_ONCE_KEY + '"', launcher)
        self.assertIn("if (background && UpdateResuming()) return 0;", launcher)

    def test_a_failing_install_is_retried_three_times_a_day_apart(self):
        now = [1_000_000]
        item = self.make(clock=lambda: now[0])
        self.assertTrue(item.check_once())
        with self.assertRaisesRegex(updater.UpdateError, 'waiting-after-failed-install'):
            item.check_once()  # The Coletor reopened with the same version: not again today.
        for _ in range(2):
            now[0] += updater.ATTEMPT_SPACING_SECONDS
            self.assertTrue(item.check_once())
        now[0] += updater.ATTEMPT_SPACING_SECONDS
        with self.assertRaisesRegex(updater.UpdateError, 'waiting-after-failed-install'):
            item.check_once()
        self.assertEqual(len(self.launched), 3)
        # A newer version starts over; once installed, the record goes.
        self.assertTrue(self.make(latest='0.4.331', clock=lambda: now[0]).check_once())
        self.assertFalse(self.make(current='0.4.331', latest='0.4.331').check_once())
        self.assertFalse((self.settings / 'atualizacao' / updater.ATTEMPTS_FILE).exists())

    def test_offline_start_removes_only_installed_or_older_downloads(self):
        folder = self.settings / 'atualizacao'
        folder.mkdir(parents=True)
        for name in ('COLETOR-v0.4.328.exe', 'COLETOR-v0.4.329.exe.part', 'COLETOR-v0.4.330.exe', 'instalacao.log'):
            (folder / name).write_bytes(b'x')
        updater.remove_other_setups(folder, up_to=(0, 4, 329))
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['COLETOR-v0.4.330.exe', 'instalacao.log'])


class Access:
    def run(self, work): return work()


class UpdateWindowTests(unittest.TestCase):
    def runtime(self, now):
        item = FrequencyRuntime(Access(), object(), object(), tempfile.mkdtemp(), clock=lambda: now)
        return item

    def schedule(self, times):
        return {'timezone': 'America/Bahia', 'rules': [
            {'weekday': d, 'enabled': True, 'times': times, 'recheck': None} for d in range(7)]}

    def test_allowed_away_from_the_agenda_and_never_during_a_run(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime(2026, 11, 16, 3, 0, tzinfo=ZoneInfo('America/Bahia')).timestamp()
        item = self.runtime(now)
        self.assertTrue(item.update_allowed())  # Never activated on this computer.
        self.assertFalse(item.update_allowed(collecting=True))  # Collecting, agenda not known yet.
        item._status = {'settings': {'schedule': self.schedule(['12:00']), 'reportSchedule': None}}
        self.assertTrue(item.update_allowed())
        # Between one collection and the next (owner decision 17/11/2026), never right before or after one.
        item._status = {'settings': {'schedule': self.schedule(['02:45', '03:05']), 'reportSchedule': None}}
        self.assertTrue(item.update_allowed())  # The next one in five minutes: time enough.
        item._status = {'settings': {'schedule': self.schedule(['03:03']), 'reportSchedule': None}}
        self.assertFalse(item.update_allowed())  # In three minutes.
        item._status = {'settings': {'schedule': self.schedule(['02:58']), 'reportSchedule': None}}
        self.assertFalse(item.update_allowed())  # Two minutes ago: its run is about to begin.
        item._status = {'settings': {'schedule': self.schedule(['02:57']), 'reportSchedule': None}}
        self.assertTrue(item.update_allowed())
        report = {'timezone': 'America/Bahia', 'enabled': True, 'every': 30, 'from': '03:02', 'to': '04:00', 'weekdays': list(range(7))}
        item._status = {'settings': {'schedule': self.schedule(['12:00']), 'reportSchedule': report}}
        self.assertFalse(item.update_allowed())  # A report in two minutes.
        item._status = {'settings': {'schedule': self.schedule(['12:00']), 'reportSchedule': None}}
        with item._operation:
            self.assertFalse(item.update_allowed())
        item._pending_slots = {'x'}
        self.assertFalse(item.update_allowed())
        item._pending_slots = set()
        item._report['running'] = True
        self.assertFalse(item.update_allowed())


class LoopTests(unittest.TestCase):
    def test_keeps_checking_after_a_failure(self):
        calls = []
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(folder, ignore_errors=True))
        item = updater.Updater('0.4.329', folder, folder, safe_now=lambda: True)
        item.check_once = lambda: calls.append(1) or (_ for _ in ()).throw(updater.UpdateError('network'))
        waits = iter([False, False, True])
        item._pause = lambda seconds: next(waits)
        thread = threading.Thread(target=item._loop)
        thread.start()
        thread.join(5)
        self.assertEqual(len(calls), 2)
        state = json.loads((folder / 'atualizacao' / updater.STATE_FILE).read_text(encoding='utf-8'))
        self.assertEqual((state['versao'], state['resultado']), ('0.4.329', 'network'))


if __name__ == '__main__':
    unittest.main()
