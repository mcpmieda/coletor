"""Unattended operation: saved Smecel login, class link, history, alerts and resume.

Synthetic accounts, classes and students only; no real login or network.
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from coletor.class_catalog import CONTEXT_KEY, LIST_PATH
from coletor.desktop_api import DesktopApi
from coletor.frequency_runtime import class_key, collection_payload
from coletor.history import CollectorHistory, RETENTION_SECONDS
from coletor.manual_session import SOURCE_ORIGIN, ManualSession, SessionError
from coletor.protected_storage import ProtectedStorage, StorageError
from coletor.resume_store import ResumeStore
from coletor.tray_winforms import hides_on_close, tray_text
from synthetic_access import SyntheticAccess
import test_frequency_runtime as base

SYNTHETIC_LOGIN = {'email': 'operador@escola.invalid', 'password': 'SYNTHETIC-PASSWORD-ONLY'}


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

    def test_login_is_ciphertext_bound_to_device_and_forgotten_on_clear(self):
        self.storage.save_credential(**SYNTHETIC_LOGIN)
        raw = (Path(self.directory.name) / 'protected-frequency-v2' / 'credential.dpapi').read_bytes()
        self.assertNotIn(SYNTHETIC_LOGIN['password'].encode(), raw)
        self.assertEqual(self.storage.load_credential(), SYNTHETIC_LOGIN)
        other = ProtectedStorage(self.directory.name, crypto=base.SyntheticCrypto(), consent=self.consent)
        other.bind(base.DEVICE, 2)
        self.assertIsNone(other.load_credential())
        self.storage.clear()
        self.assertIsNone(self.storage.load_credential())

    def test_invalid_login_is_refused(self):
        for email, password in (('sem-arroba', 'x'), ('a@b.c', ''), ('a @b.c', 'x'), ('a@b.c', 'x' * 257)):
            with self.subTest(email=email), self.assertRaises(StorageError):
                self.storage.save_credential(email, password)

    def test_consent_is_asked_once_per_device_and_again_after_logout(self):
        self.assertTrue(self.storage.enable())
        reopened = ProtectedStorage(self.directory.name, crypto=base.SyntheticCrypto(), consent=self.consent)
        reopened.bind(base.DEVICE, 1)
        self.assertTrue(reopened.enable())
        self.assertEqual(self.asked, 1)
        reopened.clear()
        reopened.bind(base.DEVICE, 1)
        reopened.enable()
        self.assertEqual(self.asked, 2)


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
        self.assertEqual(tray_text({'active': True, 'state': 'collecting'}, 'idle'), 'Coletor de Frequência · Coletando')
        self.assertEqual(tray_text(None, 'error'), 'Coletor · Coleta desligada · Arquivo precisa de atenção')
        for state in ('ready', 'reserve', 'collecting', 'paused', 'login-required', 'error'):
            self.assertLessEqual(len(tray_text({'active': True, 'state': state}, 'idle')), 63)

    def test_window_close_keeps_an_active_collection_beside_the_clock(self):
        active = {'active': True, 'state': 'ready'}
        self.assertTrue(hides_on_close(True, False, active, True))
        self.assertFalse(hides_on_close(True, True, active, True))  # Sair in the tray menu.
        self.assertFalse(hides_on_close(False, False, active, True))  # Windows shutdown or logoff.
        self.assertFalse(hides_on_close(True, False, {'active': False, 'state': 'connect'}, True))
        self.assertFalse(hides_on_close(True, False, None, True))
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
    def page(self, accepts):
        class Locator:
            def __init__(self, page): self.page = page
            async def count(self): return 0 if self.page.signed else 1
        class Navigation:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False
        class Page:
            def __init__(self): self.signed, self.filled, self.visited = False, {}, []
            async def goto(self, url, wait_until): self.visited.append(url)
            def locator(self, selector): return Locator(self)
            async def fill(self, selector, value): self.filled[selector] = value
            def expect_navigation(self, **_): return Navigation()
            async def click(self, selector):
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
