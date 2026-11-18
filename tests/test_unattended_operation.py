"""Unattended operation: saved Smecel login, class link, history, alerts and resume.

Synthetic accounts, classes and students only; no real login or network.
"""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from coletor.class_catalog import CONTEXT_KEY, LIST_PATH
from coletor.desktop_api import DesktopApi
from coletor.frequency_runtime import class_key, collection_payload
from coletor.history import CollectorHistory, RETENTION_SECONDS
from coletor.manual_session import SOURCE_ORIGIN, ManualSession, SessionError
from coletor.protected_storage import ProtectedStorage, StorageError, windows_question
from coletor.resume_store import ResumeStore
from coletor.tray_winforms import hides_on_close, tray_text
from synthetic_access import SyntheticAccess
import test_frequency_runtime as base

SYNTHETIC_LOGIN = {'email': 'operador@escola.invalid', 'password': 'SYNTHETIC-PASSWORD-ONLY'}
# The device the Ecossistema creates when this computer is authorized again.
NEW_DEVICE = '22222222-2222-4222-8222-222222222222'


class ClassLinkTests(unittest.TestCase):
    setUp = base.RuntimeTests.setUp
    def test_class_key_matches_the_centro_rule(self):
        self.assertEqual(class_key('8D 2026 -VESPERTINO'), class_key('8D  2026 - vespertino'))
        self.assertEqual(class_key('6º ANO A'), '6ANOA')
        self.assertEqual(class_key('Turma Sintética Ação'), 'TURMASINTETICAACAO')
        self.assertNotEqual(class_key('8D 2026 - VESPERTINO'), class_key('8E 2026 - VESPERTINO'))

    def test_payload_accepts_spacing_differences_between_smecel_pages(self):
        preview = base.preview()
        preview['snapshot']['students'][0]['original_class'] = 'TURMA  SINTÉTICA-A'
        payload = collection_payload(preview, {'class_id': '13331', 'name': 'TURMA SINTÉTICA A'},
                                     {'classId': 10, 'sourceClassLabel': 'Turma Sintetica A', 'revision': 0}, 1, base.DEVICE)
        self.assertEqual(payload['classId'], 10)

    def test_unlinked_class_does_not_stop_the_others_and_is_reported(self):
        alerts = []
        self.runtime._on_alert = alerts.append
        classes = [{'class_id': '13331', 'name': 'TURMA SINTÉTICA A', 'shift': 'matutino'},
                   {'class_id': '13332', 'name': 'TURMA SEM LIGAÇÃO', 'shift': 'matutino'}]
        self.source.operational_catalog = lambda storage: {'selected_class_ids': ['13331', '13332'],
                                                           'unavailable_class_ids': [], 'catalog': {'classes': classes}}
        result = self.runtime.collect()
        self.assertEqual(result['code'], 'CLASS_RECONCILIATION_REQUIRED')
        self.assertEqual(len([r for r in self.provider.requests if r['operation'] == 'collect']), 1)
        self.assertEqual(alerts, ['CLASS_RECONCILIATION_REQUIRED'])
        kinds = [e['kind'] for e in self.runtime.recent_history()]
        self.assertIn('class-sent', kinds)
        failure = next(e for e in self.runtime.recent_history() if e['kind'] == 'failure')
        self.assertEqual(failure['label'], 'TURMA SEM LIGAÇÃO')

    def test_no_classes_in_the_centro_is_reported_before_opening_smecel(self):
        original = self.provider.frequency_request
        def without_classes(payload):
            value = original(payload)
            if payload['operation'] == 'status': value['classes'] = []
            return value
        self.provider.frequency_request = without_classes
        self.source.operational_catalog = Mock()
        self.assertEqual(self.runtime.collect()['code'], 'CENTER_CLASSES_REQUIRED')
        self.source.operational_catalog.assert_not_called()

    def test_saved_login_retries_an_expired_session_but_a_refused_password_waits(self):
        self.storage.save_credential(**SYNTHETIC_LOGIN)
        self.source.operational_catalog = Mock(side_effect=SessionError('SOURCE_LOGIN_REQUIRED'))
        self.runtime.collect()
        self.assertFalse(self.runtime._source_blocked)
        self.source.operational_catalog = Mock(side_effect=SessionError('SOURCE_LOGIN_FAILED'))
        self.assertEqual(self.runtime.collect()['code'], 'SOURCE_LOGIN_FAILED')
        self.assertTrue(self.runtime._source_blocked)

    def _agenda_now(self, minutes_later=0):
        """Today's matutino agenda with a slot now (and one some minutes later, when asked)."""
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        zone = ZoneInfo('America/Bahia')
        at = lambda offset: datetime.fromtimestamp(self.provider.now + offset, timezone.utc).astimezone(zone)
        value = base.schedule()
        for r in value['rules']: r.update(enabled=False, times=[], recheck=None)
        rule = next(r for r in value['rules'] if r['weekday'] == (at(0).weekday() + 1) % 7 and r['shift'] == 'matutino')
        rule.update(enabled=True, times=sorted({at(0).strftime('%H:%M'), at(minutes_later * 60).strftime('%H:%M')}))
        self.provider.shared_schedule = value

    def _wait_idle(self):
        import time
        deadline = time.monotonic() + 2
        time.sleep(.02)
        while self.runtime._operation.locked() and time.monotonic() < deadline: time.sleep(.01)

    def test_saved_login_signs_in_again_right_away_when_the_session_expires(self):
        # Owner request 23/10/2026: read the frequency at any cost, never wait for the next slot.
        self.storage.save_credential(**SYNTHETIC_LOGIN)
        self._agenda_now()
        calls = []
        def catalog(storage):
            calls.append(1)
            if len(calls) == 1: raise SessionError('SOURCE_LOGIN_REQUIRED')
            return base.Source.operational_catalog(self.source, storage)
        self.source.operational_catalog = catalog
        self.runtime.tick()
        self._wait_idle()
        self.assertEqual(len(calls), 1)
        self.provider.now += 60  # The next minute: no slot, but a new attempt.
        self.runtime.tick()
        self._wait_idle()
        self.assertEqual(len(calls), 2)
        self.assertIsNone(self.runtime.public_status()['code'])
        self.assertTrue(any(e['kind'] == 'login-retry' for e in self.runtime.recent_history(20)))
        self.provider.now += 60  # One new attempt only: never a loop.
        self.runtime.tick()
        self._wait_idle()
        self.assertEqual(len(calls), 2)

    def test_a_new_attempt_after_an_expired_session_happens_once_per_failure(self):
        self.storage.save_credential(**SYNTHETIC_LOGIN)
        self._agenda_now()
        self.source.operational_catalog = Mock(side_effect=SessionError('SOURCE_LOGIN_REQUIRED'))
        for _ in range(4):
            self.runtime.tick()
            self._wait_idle()
            self.provider.now += 60
        self.assertEqual(self.source.operational_catalog.call_count, 2)

    def test_slots_missed_while_waiting_for_a_login_run_once_right_after_it(self):
        # No saved login: a person signs in. The slots missed meanwhile are read right after, once.
        self._agenda_now(minutes_later=15)
        self.runtime._source_blocked, self.runtime._code = True, 'SOURCE_LOGIN_REQUIRED'
        self.runtime.collect = Mock()
        self.runtime.tick()
        self.provider.now += 15 * 60
        self.runtime.tick()
        self.assertEqual(self.runtime.collect.call_count, 0)
        self.provider.now += 4 * 60  # Signed in four minutes after the last slot.
        self.runtime.source_ready()
        self.runtime.tick()
        self._wait_idle()
        self.assertEqual(self.runtime.collect.call_count, 1)
        self.assertTrue(any(e['kind'] == 'login-catch-up' for e in self.runtime.recent_history(20)))
        self.provider.now += 60
        self.runtime.tick()
        self._wait_idle()
        self.assertEqual(self.runtime.collect.call_count, 1)

    def test_saved_login_survives_a_new_authorization_and_ends_with_logout(self):
        # 17/11/2026: after "Autorizar este computador" the login had to be typed again.
        self.storage.save_credential(**SYNTHETIC_LOGIN)
        self.provider.storage_binding = lambda: (NEW_DEVICE, 1)
        self.assertEqual(self.runtime.saved_credential(), SYNTHETIC_LOGIN)
        self.assertEqual(self.storage._binding, NEW_DEVICE + ':1')
        self.assertEqual(self.runtime.public_status()['credential'], {'saved': True, 'account': 'op•••@escola.invalid'})
        self.runtime.cancel(purge=True)  # "Sair da conta".
        self.assertIsNone(self.storage.load_credential())
        self.assertFalse((self.storage.directory / 'credential.dpapi').exists())
        self.assertEqual(self.runtime.public_status()['credential'], {'saved': False})

    def test_status_never_returns_the_saved_password(self):
        self.storage.save_credential(**SYNTHETIC_LOGIN)
        status = self.runtime.public_status()
        self.assertEqual(status['credential'], {'saved': True, 'account': 'op•••@escola.invalid'})
        self.assertNotIn(SYNTHETIC_LOGIN['password'], repr(status))


class ProtectedLoginTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.asked = 0
        def consent():
            self.asked += 1
            return True
        self.consent = consent
        self.storage = ProtectedStorage(self.directory.name, crypto=base.SyntheticCrypto(), consent=consent)
        self.storage.bind(base.DEVICE, 1)

    def reopened(self, device, generation):
        """The program opened again, with the device and generation the Ecossistema now gives it."""
        storage = ProtectedStorage(self.directory.name, crypto=base.SyntheticCrypto(), consent=self.consent)
        storage.bind(device, generation)
        return storage

    def legacy(self, purpose, value, device, generation):
        """A file as the versions before 17/11/2026 wrote it: tied to the device and its generation."""
        binding = f'{device}:{generation}'
        raw = json.dumps({'version': 2, 'binding': binding, 'value': value}).encode('utf-8')
        entropy = ('Ecossistema.Coletor.Protected.v2\0' + purpose + '\0' + binding).encode('utf-8')
        self.storage.directory.mkdir(parents=True, exist_ok=True)
        path = self.storage.directory / (purpose + '.dpapi')
        path.write_bytes(b'CFV2\0' + base.SyntheticCrypto().protect(raw, entropy))
        return path

    def test_login_is_ciphertext_and_opens_after_a_new_authorization(self):
        self.storage.save_credential(**SYNTHETIC_LOGIN)
        path = self.storage.directory / 'credential.dpapi'
        self.assertNotIn(SYNTHETIC_LOGIN['password'].encode(), path.read_bytes())
        # The program reopened with a new generation, or with a new device.
        self.assertEqual(self.reopened(base.DEVICE, 2).load_credential(), SYNTHETIC_LOGIN)
        self.assertEqual(self.reopened(NEW_DEVICE, 1).load_credential(), SYNTHETIC_LOGIN)
        # The same with the program open: the new binding keeps the login, on disk too.
        self.storage.bind(NEW_DEVICE, 1)
        self.assertTrue(path.exists())
        self.assertEqual(self.storage.load_credential(), SYNTHETIC_LOGIN)
        self.assertEqual(self.storage.credential_status(), {'saved': True, 'account': 'op•••@escola.invalid'})

    def test_login_is_forgotten_on_logout_and_when_the_operator_removes_it(self):
        path = self.storage.directory / 'credential.dpapi'
        self.storage.save_credential(**SYNTHETIC_LOGIN)
        self.storage.clear()  # "Sair da conta" and "Remover acesso deste PC".
        self.assertFalse(path.exists())
        self.assertIsNone(self.storage.load_credential())
        self.assertIsNone(self.reopened(NEW_DEVICE, 1).load_credential())
        self.storage.save_credential(**SYNTHETIC_LOGIN)
        self.storage.clear_credential()
        self.assertFalse(path.exists())
        self.assertEqual(self.storage.credential_status(), {'saved': False})

    def test_login_saved_by_an_earlier_version_is_kept_while_its_device_is_the_live_one(self):
        path = self.legacy('credential', SYNTHETIC_LOGIN, base.DEVICE, 1)
        before = path.read_bytes()
        # Another device cannot open the old file, and leaves it as it is.
        self.assertIsNone(self.reopened(NEW_DEVICE, 1).load_credential())
        self.assertEqual(path.read_bytes(), before)
        # The device that saved it opens it and writes it again for the Windows user...
        self.assertEqual(self.storage.load_credential(), SYNTHETIC_LOGIN)
        self.assertNotEqual(path.read_bytes(), before)
        self.assertNotIn(SYNTHETIC_LOGIN['password'].encode(), path.read_bytes())
        # ...so the next authorization still has it.
        self.assertEqual(self.reopened(NEW_DEVICE, 1).load_credential(), SYNTHETIC_LOGIN)

    def test_session_and_copies_stay_tied_to_the_device(self):
        self.storage.enable()
        self.storage.save_session({'cookies': [], 'origins': []})
        self.storage.save_copy('schedule', {'synthetic': True})
        other = self.reopened(NEW_DEVICE, 1)
        self.assertIsNone(other.load_session())  # Not this device's: no session, never another's.
        self.assertIsNone(other.load_copy('schedule'))
        self.storage.bind(NEW_DEVICE, 1)
        self.assertFalse((self.storage.directory / 'session.dpapi').exists())
        self.assertFalse((self.storage.directory / 'copy-schedule.dpapi').exists())
        self.assertIsNone(self.storage.load_session())

    def test_invalid_login_is_refused(self):
        for email, password in (('sem-arroba', 'x'), ('a@b.c', ''), ('a @b.c', 'x'), ('a@b.c', 'x' * 257)):
            with self.subTest(email=email), self.assertRaises(StorageError):
                self.storage.save_credential(email, password)

    def test_session_of_an_earlier_authorization_is_no_session_and_is_saved_over(self):
        # 17/11/2026: the old session.dpapi stayed on disk after a new authorization with the
        # program reopened, did not open, and every run stopped with a storage error.
        self.storage.enable()
        self.storage.save_session({'cookies': [], 'origins': []})
        self.storage.save_credential(**SYNTHETIC_LOGIN)
        path = self.storage.directory / 'session.dpapi'
        stale = path.read_bytes()
        reopened = self.reopened(NEW_DEVICE, 1)
        reopened.enable()
        driver = Catalog(SYNTHETIC_LOGIN['password'])
        driver.export_state = lambda: {'cookies': [{'domain': 'www.smecel.com.br'}], 'origins': []}
        source_directory = tempfile.TemporaryDirectory(); self.addCleanup(source_directory.cleanup)
        source = ManualSession(lambda: driver, source_directory.name)
        reply = source.operational_catalog(reopened)  # Signs in with the saved login.
        self.assertEqual(driver.logins, 1)
        self.assertEqual(reply['catalog']['classes'][0]['class_id'], '13331')
        self.assertEqual(path.read_bytes(), stale)  # Reading never deletes.
        source.preserve_and_close(reopened)
        self.assertNotEqual(path.read_bytes(), stale)
        self.assertEqual(self.reopened(NEW_DEVICE, 1).load_session(),
                         {'cookies': [{'domain': 'www.smecel.com.br'}], 'origins': []})

    def test_session_of_an_earlier_authorization_without_a_saved_login_asks_a_person(self):
        self.storage.enable()
        self.storage.save_session({'cookies': [], 'origins': []})
        driver = Catalog(SYNTHETIC_LOGIN['password'])
        source_directory = tempfile.TemporaryDirectory(); self.addCleanup(source_directory.cleanup)
        with self.assertRaisesRegex(SessionError, 'SOURCE_LOGIN_REQUIRED'):
            ManualSession(lambda: driver, source_directory.name).operational_catalog(self.reopened(NEW_DEVICE, 1))
        self.assertIsNone(driver.opened)

    def test_session_errors_that_are_not_an_earlier_authorization_still_show(self):
        self.storage.enable()
        self.storage.save_session({'cookies': [], 'origins': []})
        path = self.storage.directory / 'session.dpapi'
        saved = path.read_bytes()
        # Windows protection not answering (a moment at logon): the error stands, to try again.
        failing = self.reopened(NEW_DEVICE, 1)
        failing._crypto = Mock(protect=Mock(side_effect=StorageError()), unprotect=Mock(side_effect=StorageError()))
        with self.assertRaises(StorageError): failing.load_session()
        # Not one of the Coletor's files, and a storage with no live binding.
        path.write_bytes(b'not-a-protected-file')
        with self.assertRaises(StorageError): self.storage.load_session()
        path.write_bytes(saved)
        unbound = ProtectedStorage(self.directory.name, crypto=base.SyntheticCrypto(), consent=self.consent)
        with self.assertRaises(StorageError): unbound.load_session()
        # A saved session with a cookie of another site is refused, never used.
        other_site = json.dumps({'version': 2, 'binding': base.DEVICE + ':1',
                                 'value': {'cookies': [{'domain': 'evil.invalid'}], 'origins': []}}).encode('utf-8')
        entropy = ('Ecossistema.Coletor.Protected.v2\0session\0' + base.DEVICE + ':1').encode('utf-8')
        path.write_bytes(b'CFV2\0' + base.SyntheticCrypto().protect(other_site, entropy))
        with self.assertRaises(StorageError): self.storage.load_session()

    def test_consent_is_asked_once_per_windows_user_and_again_after_logout(self):
        self.assertTrue(self.storage.enable())
        self.assertTrue(self.reopened(base.DEVICE, 1).enable())
        # A new authorization does not ask again, with the program reopened or still open.
        renewed = self.reopened(NEW_DEVICE, 1)
        self.assertTrue(renewed.enable())
        self.storage.bind(NEW_DEVICE, 1)
        self.assertTrue(self.storage.persistent)
        self.assertEqual(self.asked, 1)
        renewed.clear()
        renewed.bind(NEW_DEVICE, 1)
        renewed.enable()
        self.assertEqual(self.asked, 2)

    def test_windows_question_opens_in_front_with_no_as_the_default(self):
        # 17/11/2026: the box opened behind the other windows and nobody answered it.
        with patch('coletor.protected_storage.os') as system, patch('coletor.protected_storage.ctypes') as native:
            system.name = 'nt'
            box = native.windll.user32.MessageBoxW
            box.return_value = 6  # Yes.
            self.assertTrue(windows_question('Pergunta sintética?', 'Título sintético'))
            owner, message, title, flags = box.call_args.args
            self.assertEqual((owner, message, title), (None, 'Pergunta sintética?', 'Título sintético'))
            yes_no, no_is_default, set_foreground, topmost = 0x4, 0x100, 0x10000, 0x40000
            for flag in (yes_no, no_is_default, set_foreground, topmost):
                self.assertEqual(flags & flag, flag)
            box.return_value = 7  # No.
            self.assertFalse(windows_question('Pergunta sintética?', 'Título sintético'))

    def test_consent_answered_in_an_earlier_version_is_not_asked_again(self):
        self.legacy('consent', {'persistent': True}, base.DEVICE, 1)
        self.assertTrue(self.storage.enable())
        self.assertTrue(self.reopened(NEW_DEVICE, 1).enable())
        self.assertEqual(self.asked, 0)


class Catalog:
    def __init__(self, password):
        self.password, self.logged_in, self.logins = password, False, 0
        self.opened = None

    def open(self, url): self.opened = url
    def close(self): pass

    def login(self, email, password):
        self.logins += 1
        self.logged_in = password == self.password
        return self.logged_in

    def discover(self, year):
        if not self.logged_in: raise RuntimeError('listing_changed')
        return {'scope': {'origin': SOURCE_ORIGIN, 'list_path': LIST_PATH, 'year': year, 'context_key': CONTEXT_KEY},
                'classes': [{'class_id': '13331', 'year': year, 'name': 'TURMA SINTÉTICA A', 'stage': '6',
                             'matrix': 'M', 'shift': 'Manhã'}], 'context_label': 'Sintético', 'filtered': False}


class Storage:
    def __init__(self, credential): self.credential = credential
    def load_session(self): return None
    def load_credential(self): return self.credential


class SmecelSignInTests(unittest.TestCase):
    def session(self, driver):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        return ManualSession(lambda: driver, directory.name)

    def test_saved_login_opens_the_class_list(self):
        driver = Catalog(SYNTHETIC_LOGIN['password'])
        reply = self.session(driver).operational_catalog(Storage(SYNTHETIC_LOGIN))
        self.assertEqual(driver.logins, 1)
        self.assertEqual(reply['catalog']['classes'][0]['class_id'], '13331')

    def test_refused_password_is_not_retried_in_a_loop(self):
        driver = Catalog('another-password')
        with self.assertRaisesRegex(SessionError, 'SOURCE_LOGIN_FAILED'):
            self.session(driver).operational_catalog(Storage(SYNTHETIC_LOGIN))
        self.assertEqual(driver.logins, 1)

    def test_without_saved_login_or_session_a_person_is_needed(self):
        driver = Catalog(SYNTHETIC_LOGIN['password'])
        with self.assertRaisesRegex(SessionError, 'SOURCE_LOGIN_REQUIRED'):
            self.session(driver).operational_catalog(Storage(None))
        self.assertIsNone(driver.opened)


class HistoryTests(unittest.TestCase):
    def test_keeps_only_operational_facts_for_thirty_days(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        now = [1_800_000_000.0]
        history = CollectorHistory(directory.name, clock=lambda: now[0])
        history.record('class-sent', label='TURMA  SINTÉTICA A', sent=3, unresolved=1, conflicts=0, code='x' * 90)
        history.record('unknown-kind', label='ignored')
        now[0] += RETENTION_SECONDS + 1
        history.record('failure', code='SOURCE_LOGIN_REQUIRED')
        self.assertEqual([e['kind'] for e in history.recent()], ['failure'])
        now[0] -= RETENTION_SECONDS
        entry = CollectorHistory(directory.name, clock=lambda: now[0]).recent()
        self.assertEqual(entry[0]['code'], 'SOURCE_LOGIN_REQUIRED')


class TrayAndResumeTests(unittest.TestCase):
    def test_tooltip_shows_collection_state_within_the_tray_limit(self):
        self.assertEqual(tray_text({'active': True, 'state': 'collecting'}, 'idle'), 'Coletor · Coletando')
        self.assertEqual(tray_text(None, 'error'), 'Coletor · Coleta desligada · Arquivo precisa de atenção')
        # A short outage is a calm wait, not the red "needs attention" state.
        offline = tray_text({'active': True, 'state': 'reserve', 'code': 'ACCESS_UNAVAILABLE'}, 'idle')
        self.assertEqual(offline, 'Coletor · Sem conexão, tentando de novo')
        self.assertLessEqual(len(offline), 63)
        self.assertEqual(tray_text({'active': True, 'state': 'error', 'code': 'lease-fenced'}, 'idle'),
                         'Coletor · Precisa de atenção')
        # The catch-all code is a real fault, never shown as a harmless outage.
        self.assertEqual(tray_text({'active': True, 'state': 'error', 'code': 'unavailable'}, 'idle'),
                         'Coletor · Precisa de atenção')
        for state in ('ready', 'reserve', 'collecting', 'paused', 'login-required', 'error'):
            self.assertLessEqual(len(tray_text({'active': True, 'state': state}, 'idle')), 63)

    def test_window_close_keeps_an_active_collection_beside_the_clock(self):
        active = {'active': True, 'state': 'ready'}
        self.assertTrue(hides_on_close(True, False, active, True))
        self.assertFalse(hides_on_close(True, True, active, True))  # Sair in the tray menu.
        self.assertFalse(hides_on_close(False, False, active, True))  # Windows shutdown or logoff.
        self.assertTrue(hides_on_close(True, False, {'active': False, 'state': 'connect'}, True))
        self.assertTrue(hides_on_close(True, False, {'active': True, 'state': 'paused'}, True))
        self.assertTrue(hides_on_close(True, False, None, True))  # Status unavailable during reconnection.
        self.assertFalse(hides_on_close(True, False, active, False))  # No icon to come back from.

    def test_resume_flag_follows_activation_and_pause(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        store = ResumeStore(directory.name)
        self.assertFalse(store.active())
        store.set(True); self.assertTrue(ResumeStore(directory.name).active())
        store.set(False); self.assertFalse(store.active())

    def test_reopening_resumes_only_an_active_collection(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        api = DesktopApi(Path(directory.name), access=SyntheticAccess())
        api._collector.activate = Mock(return_value={'state': 'reserve'})
        self.assertFalse(api._resume_collection(attempts=1, interval=0))
        api._collector.activate.assert_not_called()
        api._resume.set(True)
        api._access.status = Mock(return_value={'authenticated': True, 'authorized': True})
        self.assertTrue(api._resume_collection(attempts=1, interval=0))
        api._collector.activate.assert_called_once()

    def test_new_authorization_resumes_a_collection_left_active(self):
        # 17/11/2026: after "Autorizar este computador" the collection stayed off until "Ativar".
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        api = DesktopApi(Path(directory.name), access=SyntheticAccess())
        api._start_resume = Mock()
        active = {'active': False}
        api._collector.public_status = lambda: dict(active)
        refused = {'authenticated': False, 'authorized': False, 'code': 'ACCESS_REQUIRED'}
        authorized = {'authenticated': True, 'authorized': True}
        api._resume.set(True)
        api._access.status = Mock(return_value=refused)
        self.assertEqual(api.get_institutional_access_status(), refused)
        api._start_resume.assert_not_called()
        api._access.status = Mock(return_value=authorized)
        self.assertEqual(api.get_institutional_access_status(), authorized)
        api._start_resume.assert_called_once()
        # Already collecting, or left off by a pause or a logout: nothing to start.
        active['active'] = True
        api.get_institutional_access_status()
        active['active'] = False
        api._resume.set(False)
        api.get_institutional_access_status()
        api._start_resume.assert_called_once()

    def test_resume_runs_one_at_a_time(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        api = DesktopApi(Path(directory.name), access=SyntheticAccess())
        api._resume.set(True)
        started, finish = threading.Event(), threading.Event()
        def activate():
            started.set()
            finish.wait(5)
            return {'state': 'reserve'}
        api._collector.activate = Mock(side_effect=activate)
        api._start_resume()
        self.assertTrue(started.wait(5))
        api._start_resume()  # The opening of the program and a new authorization at once.
        finish.set()
        api._resume_thread.join(5)
        self.assertFalse(api._resume_thread.is_alive())
        api._collector.activate.assert_called_once()

    def test_long_offline_boot_keeps_trying_and_activates_without_restart(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        api = DesktopApi(Path(directory.name), access=SyntheticAccess())
        api._resume.set(True)
        api._collector.activate = Mock(return_value={'state': 'reserve'})
        answers = [{'authenticated': False, 'authorized': False, 'code': 'ACCESS_UNAVAILABLE'}] * 31
        answers.append({'authenticated': True, 'authorized': True})
        api._access.status = Mock(side_effect=answers)
        api._resume_stop.wait = Mock(return_value=False)  # No real sleeping.
        self.assertTrue(api._resume_collection(interval=0))
        api._collector.activate.assert_called_once()
        # Waits back off after the first half hour, never beyond 15 minutes.
        waits = [c.args[0] for c in api._resume_stop.wait.call_args_list]
        self.assertTrue(all(w <= 900 for w in waits))

    def test_offline_resume_stops_on_pause_or_exit(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        api = DesktopApi(Path(directory.name), access=SyntheticAccess())
        api._resume.set(True)
        api._access.status = Mock(return_value={'authenticated': False, 'authorized': False, 'code': 'ACCESS_UNAVAILABLE'})
        api._resume_stop.set()
        self.assertFalse(api._resume_collection(interval=0))
        self.assertEqual(api._access.status.call_count, 1)

    def test_refused_logout_keeps_the_offline_retry_alive(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        api = DesktopApi(Path(directory.name), access=SyntheticAccess())
        api._pending_batch_blocker = Mock(return_value={'error': 'pendente', 'code': 'PENDING_BATCHES'})
        self.assertEqual(api.logout_institutional_access()['code'], 'PENDING_BATCHES')
        self.assertFalse(api._resume_stop.is_set())

    def test_failed_class_choice_opening_resumes_collection(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        api = DesktopApi(Path(directory.name), access=SyntheticAccess())
        api._collector.public_status = Mock(return_value={'active': True, 'localPaused': False})
        api._collector.local_pause = Mock(return_value={'state': 'ready'})
        api._manual = Mock(return_value={'error': 'Há uma coleta em andamento.'})
        api._operational = lambda work: work()
        self.assertIn('error', api.prepare_manual_login(2026))
        self.assertEqual([c.args for c in api._collector.local_pause.call_args_list], [(True,), (False,)])
        self.assertFalse(api._paused_for_choice)

    def test_operator_pause_during_the_choice_is_not_undone(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        api = DesktopApi(Path(directory.name), access=SyntheticAccess())
        api._paused_for_choice = True
        api._operational = lambda work: {'state': 'paused'}
        api.pause_collector(True)
        self.assertFalse(api._paused_for_choice)

    def test_tray_notifications_switch_saves_without_online_check(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        api = DesktopApi(Path(directory.name), access=SyntheticAccess())
        api._set_notifications(False)
        self.assertFalse(api._notifications_on())
        api._set_notifications(True)
        self.assertTrue(api._notifications_on())

    def test_alert_waits_for_the_tray_and_then_shows_a_balloon(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        api = DesktopApi(Path(directory.name), access=SyntheticAccess())
        api._alert('SOURCE_LOGIN_REQUIRED')
        tray = Mock()
        api._attach_tray(tray)
        tray.notify.assert_called_once_with('Smecel desconectado', 'Abra o Coletor e entre no Smecel para continuar a coleta.')


if __name__ == '__main__':
    unittest.main()


class SignInFormTests(unittest.TestCase):
    def page(self, accepts, modal=False):
        class Locator:
            def __init__(self, page): self.page = page
            async def count(self): return 0 if self.page.signed else 1
            async def is_visible(self): return not self.page.hidden
        class Navigation:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False
        class Page:
            def __init__(self):
                self.signed, self.filled, self.visited = False, {}, []
                self.hidden, self.clicks = modal, []
            async def goto(self, url, wait_until): self.visited.append(url)
            def locator(self, selector): return Locator(self)
            async def fill(self, selector, value):
                if self.hidden: raise RuntimeError('login-form-hidden')
                self.filled[selector] = value
            def expect_navigation(self, **_): return Navigation()
            async def click(self, selector):
                self.clicks.append(selector)
                if selector == 'button[onclick="abrirModal()"]:visible':
                    self.hidden = False
                    return
                self.signed = accepts and self.filled.get('#senha') == SYNTHETIC_LOGIN['password']
        return Page()

    def test_fills_only_the_observed_smecel_fields(self):
        import asyncio
        from coletor.manual_worker import LOGIN_URL, sign_in
        page = self.page(True)
        self.assertEqual(asyncio.run(sign_in(page, **SYNTHETIC_LOGIN)), {'logged_in': True})
        self.assertEqual(page.visited, [LOGIN_URL])
        self.assertEqual(page.filled, {'#usuario': SYNTHETIC_LOGIN['email'], '#senha': SYNTHETIC_LOGIN['password']})
        self.assertEqual(asyncio.run(sign_in(self.page(False), **SYNTHETIC_LOGIN)), {'logged_in': False})

    def test_reuses_the_login_page_only_when_the_worker_says_it_is_fresh(self):
        import asyncio
        from coletor.manual_worker import LOGIN_URL, sign_in
        page = self.page(True); page.url = LOGIN_URL
        self.assertEqual(asyncio.run(sign_in(page, **SYNTHETIC_LOGIN, reload=False)), {'logged_in': True})
        self.assertEqual(page.visited, [])
        page = self.page(True); page.url = LOGIN_URL
        asyncio.run(sign_in(page, **SYNTHETIC_LOGIN))
        self.assertEqual(page.visited, [LOGIN_URL])
        page = self.page(True); page.url = 'https://www.smecel.com.br/sistema/escola/turmaListar.php?ano=2026'
        asyncio.run(sign_in(page, **SYNTHETIC_LOGIN, reload=False))
        self.assertEqual(page.visited, [LOGIN_URL])

    def test_opens_hidden_administrative_login_before_filling_saved_credentials(self):
        import asyncio
        from coletor.manual_worker import LOGIN_FIELDS, LOGIN_OPENER, sign_in
        page = self.page(True, modal=True)
        self.assertEqual(asyncio.run(sign_in(page, **SYNTHETIC_LOGIN)), {'logged_in': True})
        self.assertEqual(page.clicks, [LOGIN_OPENER, LOGIN_FIELDS[2]])
