"""Synthetic source scope, consent, cancellation and privacy regressions."""
import json
from pathlib import Path
import re
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from coletor.demo import build_fixture
from coletor.manual_session import ManualSession, SessionError, allowed_request, captured_preview, matches_source, source_url
from coletor.manual_worker import BrowserWorker


def raw_fixture():
    return re.sub(r' data-(?:report|class-id|year|student-count|student-row|report-end)="[^"]*"', '',
                  build_fixture(include_edge_cases=False))


class Driver:
    def __init__(self):
        self.opened = False
        self.closed = False
        self.payload = {"url": source_url("13331", 2026), "html": raw_fixture(), "password_form": False}

    def open(self, url):
        self.opened = True

    def capture(self):
        return self.payload

    def close(self):
        self.closed = True


class ManualSessionTests(unittest.TestCase):
    def setUp(self):
        self.driver = Driver()
        self.session = ManualSession(lambda: self.driver)

    def opened(self):
        prepared = self.session.prepare("13331", 2026)
        self.session.open(prepared["generation"], True)
        return prepared["generation"]

    def test_scope_is_numeric_and_exact_without_guessing_login_endpoint(self):
        for ct in ("TESTE-A", "01", "1&token=SECRET", "", 1, "1/other"):
            with self.subTest(ct=ct), self.assertRaises(SessionError):
                source_url(ct, 2026)
        for year in (True, "2026", 1999, 2101):
            with self.assertRaises(SessionError):
                source_url("13331", year)
        url = source_url("13331", 2026)
        self.assertTrue(matches_source(url, "13331", 2026))
        for bad in (url.replace("https:", "http:"), url.replace("www.smecel.com.br", "www.smecel.com.br.evil.test"),
                    url + "&ct=13331", url + "&token=SECRET", url + "#SECRET", url.replace("13331", "13332"),
                    url.replace("2026", "2025"), url.replace("www.", "SECRET@www.")):
            with self.subTest(url=bad):
                self.assertFalse(matches_source(bad, "13331", 2026))
        self.assertFalse(allowed_request("https://www.smecel.com.br:444/x"))
        self.assertFalse(allowed_request("https://www.smecel.com.br:notaport/x"))
        self.assertFalse(allowed_request("data:text/html,SECRET"))

    def test_prepare_and_invalid_consent_do_not_open_or_capture(self):
        prepared = self.session.prepare("13331", 2026)
        self.assertFalse(self.driver.opened)
        for confirmation in (False, 1, "true", None):
            with self.assertRaises(SessionError):
                self.session.open(prepared["generation"], confirmation)
        self.assertFalse(self.driver.opened)
        self.session.open(prepared["generation"], True)
        with self.assertRaises(SessionError):
            self.session.capture(prepared["generation"], False)

    def test_manual_preview_never_claims_identity_completeness_or_transmission(self):
        generation = self.opened()
        result = self.session.capture(generation, True)
        output = result["preview"]
        self.assertEqual(output["mode"], "manual")
        self.assertEqual(len(output["snapshot"]["students"]), 3)
        self.assertFalse(output["validation"]["allowed"])
        self.assertFalse(output["capture"]["identity_verified"])
        self.assertFalse(output["capture"]["roster_complete_verified"])
        self.assertEqual(output["capture"]["destination"], "local_memory")
        self.assertNotIn("html", output)
        encoded = json.dumps(output)
        self.assertNotIn("Nascimento", encoded)
        self.assertNotIn("Filiação", encoded)
        self.assertNotIn("cookies", encoded)

    def test_login_wrong_scope_incomplete_and_synthetic_source_discard_result(self):
        generation = self.opened()
        for payload in ({**self.driver.payload, "password_form": True},
                        {**self.driver.payload, "url": source_url("13332", 2026)},
                        {**self.driver.payload, "html": raw_fixture()[:1000]},
                        {**self.driver.payload, "html": build_fixture()},
                        {**self.driver.payload, "html": "<html>SECRET</html>"}):
            self.driver.payload = payload
            with self.assertRaises(SessionError) as caught:
                self.session.capture(generation, True)
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertEqual(self.session.status()["state"], "awaiting_user")

    def test_replaced_generation_cannot_open_or_read(self):
        old = self.opened()
        new = self.session.prepare("13331", 2026)
        self.assertTrue(self.driver.closed)
        self.assertGreater(new["generation"], old)
        with self.assertRaises(SessionError):
            self.session.open(old, True)
        with self.assertRaises(SessionError):
            self.session.capture(old, True)

    def test_cancel_during_capture_rejects_late_result_and_closes_only_owned_driver(self):
        generation = self.opened()
        started, finish = threading.Event(), threading.Event()
        def delayed():
            started.set()
            finish.wait(5)
            return self.driver.payload
        self.driver.capture = delayed
        results = []
        def read():
            try:
                results.append(self.session.capture(generation, True))
            except SessionError:
                results.append("discarded")
        thread = threading.Thread(target=read)
        thread.start()
        self.assertTrue(started.wait(5))
        self.session.close()
        finish.set()
        thread.join(5)
        self.assertEqual(results, ["discarded"])
        self.assertEqual(self.session.status()["state"], "closed")
        self.assertIsNone(self.session.status()["scope"])
        self.assertTrue(self.driver.closed)

    def test_cancel_before_browser_launch_prevents_network(self):
        worker = BrowserWorker()
        worker.close()
        with self.assertRaises(RuntimeError):
            worker.open(source_url("13331", 2026))
        self.assertIsNone(worker._process)
        self.assertIsNone(worker._temporary)

    def test_gui_launcher_uses_pipe_capable_sibling_interpreter_without_console(self):
        with patch('coletor.manual_worker.sys.executable', str(Path('portable') / 'pythonw.exe')):
            command = BrowserWorker()._command()
        self.assertEqual(Path(command[0]).name, 'python.exe')
        self.assertEqual(command[1:], ['-m', 'coletor.manual_worker'])

    def test_operational_failure_is_redacted_and_session_closed(self):
        def failed(_url):
            raise OSError("SECRET PASSWORD PATH")
        self.driver.open = failed
        generation = self.session.prepare("13331", 2026)["generation"]
        with self.assertRaises(SessionError) as caught:
            self.session.open(generation, True)
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertTrue(self.driver.closed)
        self.assertEqual(self.session.status()["state"], "closed")


if __name__ == "__main__":
    unittest.main()
