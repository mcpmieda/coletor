"""Operator-authorized, ephemeral manual source session. No authentication claim."""
from datetime import datetime, timezone
import hashlib
import re
import threading
from urllib.parse import parse_qsl, urlsplit

from .service import preview

SOURCE_ORIGIN = "https://www.smecel.com.br"
SOURCE_PATH = "/sistema/escola/diario_frequencia.php"
NOTICE = "Entre no site na janela separada. O programa não confirma sua identidade nem a escola."


class SessionError(ValueError):
    pass


def source_url(class_id, year):
    if not isinstance(class_id, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", class_id):
        raise SessionError("Informe o código numérico da turma no Smecel.")
    if type(year) is not int or not 2000 <= year <= 2100:
        raise SessionError("Informe um ano entre 2000 e 2100.")
    return f"{SOURCE_ORIGIN}{SOURCE_PATH}?ct={class_id}&ano={year}"


def allowed_request(url):
    try:
        parts = urlsplit(url)
        return (parts.scheme == "https" and parts.hostname == "www.smecel.com.br"
                and parts.port in (None, 443) and not parts.username and not parts.password)
    except ValueError:
        return False


def matches_source(url, class_id, year):
    if not allowed_request(url):
        return False
    parts = urlsplit(url)
    return (parts.path == SOURCE_PATH and not parts.fragment
            and sorted(parse_qsl(parts.query, keep_blank_values=True))
            == sorted([("ct", class_id), ("ano", str(year))]))


def captured_preview(payload, class_id, year, *, allow_partial=False):
    if not isinstance(payload, dict) or not matches_source(payload.get("url", ""), class_id, year):
        raise SessionError("A janela não está no diário da turma e do ano confirmados. Confira o site.")
    if payload.get("password_form"):
        raise SessionError("A página solicita entrada no site. Faça o login na janela separada e confira o diário.")
    html = payload.get("html")
    result = preview(html, class_id, year, "manual")
    snapshot = result["snapshot"]
    permitted = {"CLASS_ID_UNVERIFIED", "ROSTER_COMPLETENESS_UNVERIFIED"}
    if allow_partial:
        permitted |= {'SOURCE_SYMBOL_UNKNOWN', 'GRID_COVERAGE_INVALID', 'TOTALS_ROW_INVALID'}
    if (snapshot["source_format"] != "smecel-annual-v1" or not snapshot["students"]
            or any(i["severity"] == "error" and i["code"] not in permitted for i in snapshot["issues"])):
        raise SessionError("O diário não passou pela conferência estrutural. Nenhum resultado parcial foi mantido.")
    result["capture"] = {"source_url": source_url(class_id, year),
                         "captured_at": datetime.now(timezone.utc).isoformat(),
                         "html_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
                         "observed_students": len(snapshot["students"]),
                         "identity_verified": False, "roster_complete_verified": False,
                         "destination": "local_memory"}
    return result


class ManualSession:
    def __init__(self, driver_factory=None, settings_directory=None):
        if driver_factory is None:
            from .manual_worker import BrowserWorker
            driver_factory = BrowserWorker
        self._factory = driver_factory
        self._lock = threading.Lock()
        self._generation = 0
        self._driver = None
        self._state = "closed"
        self._scope = None
        self._catalog = None
        self._mode = "annual"
        from .class_selection import ClassSelectionStore
        from .local_settings import LocalSettings
        self._selections = ClassSelectionStore(settings_directory)
        self._preferences = LocalSettings(settings_directory)

    def _browser_hidden(self, can_sign_in):
        """Hidden only when the Coletor can sign in by itself; a person must be
        able to see the Smecel window to sign in manually."""
        try: visible = self._preferences.read()["settings"]["browser"]["visible"]
        except (OSError, KeyError, TypeError): visible = False
        return can_sign_in and not visible

    def _new_driver(self, can_sign_in):
        driver = self._factory()
        if hasattr(driver, "hidden"): driver.hidden = self._browser_hidden(can_sign_in)
        return driver

    def _all_classes(self):
        """'Todas as turmas' (default): every class of the current list, so a new
        Smecel class is collected without anyone choosing it."""
        try: return self._preferences.read()["settings"]["classes"]["mode"] == "all"
        except (OSError, KeyError, TypeError): return True

    def prepare_login(self, year):
        from .class_catalog import list_url
        url = list_url(year)
        self.close()
        with self._lock:
            if self._state != "closed" or self._driver is not None:
                raise SessionError("A sessão anterior ainda está sendo encerrada.")
            self._mode = "list"
            self._scope = {"year": year, "url": url}
            self._state = "prepared"
            return self._status()

    def _catalog_reply(self):
        from .class_selection import revalidate_choices
        saved = self._selections.read(self._catalog["scope"])
        available = [c["class_id"] for c in self._catalog["classes"]]
        choices = revalidate_choices(saved["selection"], self._catalog["scope"], available)
        if self._all_classes():
            choices = {"selected_class_ids": available, "unavailable_class_ids": [], "context_matches": True, "all_classes": True}
        return {"session": self._status(), "catalog": self._catalog, **choices,
                "selection_revision": saved["local_revision"], "notice": saved["notice"]}

    def discover(self, generation, confirmed):
        with self._lock:
            self._check(generation, confirmed, {"awaiting_user", "list_ready", "preview_ready"})
            if self._mode != "list":
                raise SessionError("Prepare o acesso à lista de turmas primeiro.")
            self._catalog = None
            self._state = "discovering"
            driver, year = self._driver, self._scope["year"]
        try:
            catalog = driver.discover(year)
            with self._lock:
                self._check(generation, True, {"discovering"})
                from .class_catalog import CONTEXT_KEY, LIST_PATH
                if (catalog.get("scope") != {"origin": SOURCE_ORIGIN, "list_path": LIST_PATH,
                                            "year": year, "context_key": CONTEXT_KEY}
                        or not catalog.get("classes")):
                    raise SessionError("A lista não corresponde ao contexto e ano solicitados.")
                self._catalog = catalog
                self._state = "list_ready"
                return self._catalog_reply()
        except Exception:
            with self._lock:
                if generation == self._generation:
                    self._catalog = None
                    self._state = "awaiting_user"
            raise SessionError("Não foi possível reconhecer a lista deste ano/contexto. Confira o Smecel e limpe a busca da lista. Suas escolhas salvas foram preservadas.") from None

    def save_choices(self, generation, ids, revision, clear=False):
        from .class_selection import validate_ids
        ids = validate_ids(ids)
        with self._lock:
            self._check(generation, True, {"list_ready", "preview_ready"})
            available = {c["class_id"] for c in self._catalog["classes"]}
            if any(key not in available for key in ids):
                raise SessionError("Escolha somente turmas da lista atual.")
            saved = self._selections.read(self._catalog["scope"])
            # An absent/filtered row is not a revocation receipt. Preserve its
            # choice unless the operator explicitly clears this context/year.
            pending = set(saved["selection"]["selected_class_ids"]) - available if saved["selection"] and not clear else set()
            self._selections.save(self._catalog["scope"], list(set(ids) | pending), revision)
            return self._catalog_reply()

    def capture_selected(self, generation, class_id, confirmed, *, _operational=False):
        with self._lock:
            self._check(generation, confirmed, {"list_ready", "preview_ready"})
            choices = self._catalog_reply()["selected_class_ids"]
            if class_id not in choices:
                raise SessionError("Selecione uma turma disponível nesta sessão antes de ler.")
            self._state = "capturing"
            driver, year, context = self._driver, self._scope["year"], self._catalog["scope"]["context_key"]
        try:
            # Worker checks the fresh listing again immediately before opening
            # the annual diary. A saved selection never authorizes this itself.
            result = captured_preview(driver.capture_selected(class_id, year, context), class_id, year, allow_partial=_operational)
            with self._lock:
                self._check(generation, True, {"capturing"})
                self._state = "preview_ready"
                return {"session": self._status(), "preview": result}
        except Exception:
            with self._lock:
                if generation == self._generation:
                    self._catalog = None
                    self._state = "awaiting_user"
            raise SessionError("A turma não passou pela revalidação da lista e do diário. Carregue as turmas novamente; a seleção salva foi preservada.") from None

    def _status(self):
        return {"generation": self._generation, "state": self._state,
                "scope": self._scope, "identity_verified": False,
                "transmission_enabled": False, "notice": NOTICE,
                "cleanup_pending": self._state == "closed" and self._driver is not None}

    def status(self):
        with self._lock:
            return self._status()

    def sign_in(self, credential):
        """Fill the saved Smecel login in the open isolated Edge.

        Raises SOURCE_LOGIN_FAILED only when Smecel kept the login form after
        the submission (refused e-mail/password): repeating it could lock the
        account, so the scheduler waits for a person. Other failures are an
        unavailable source and are retried at the next scheduled time."""
        with self._lock:
            driver, state = self._driver, self._state
        if driver is None or state not in {'awaiting_user', 'list_ready', 'preview_ready'}:
            raise SessionError('SOURCE_LOGIN_REQUIRED')
        try:
            accepted = driver.login(credential['email'], credential['password'])
        except Exception:
            raise SessionError('SOURCE_LOGIN_REQUIRED') from None
        if not accepted: raise SessionError('SOURCE_LOGIN_FAILED')

    def has_saved_class_selection(self):
        """Local scheduling hint, never proof that a source class is still available.

        Check the exact current Smecel context without opening Edge or reading
        protected credentials. operational_catalog() still revalidates the live
        list before any capture or upload.
        """
        from .class_catalog import CONTEXT_KEY, LIST_PATH
        scope = {"origin": SOURCE_ORIGIN, "list_path": LIST_PATH,
                 "year": 2026, "context_key": CONTEXT_KEY}
        if self._all_classes(): return True
        saved = self._selections.read(scope)["selection"]
        return bool(saved and saved["selected_class_ids"])

    def saved_class_count(self):
        """How many classes are saved for the current context; display only.
        None means every class of the school ('Todas as turmas')."""
        if self._all_classes(): return None
        from .class_catalog import CONTEXT_KEY, LIST_PATH
        scope = {"origin": SOURCE_ORIGIN, "list_path": LIST_PATH,
                 "year": 2026, "context_key": CONTEXT_KEY}
        saved = self._selections.read(scope)["selection"]
        return len(saved["selected_class_ids"]) if saved else 0

    def operational_catalog(self, storage):
        """Python-only collection adapter; never accepts HTML/catalog from UI."""
        credential = storage.load_credential() if hasattr(storage, 'load_credential') else None
        with self._lock:
            driver, state, scope = self._driver, self._state, self._scope
        if driver is None:
            saved = storage.load_session()
            if saved is None and credential is None: raise SessionError('SOURCE_LOGIN_REQUIRED')
            prepared = self.prepare_login(2026)
            # Supply restored state before the isolated worker is started.
            driver = self._new_driver(credential is not None)
            if saved is not None: driver._storage_state = saved
            with self._lock:
                self._check(prepared['generation'], True, {'prepared'})
                self._driver = driver
                self._state = 'opening'
            try:
                driver.open(prepared['scope']['url'])
                with self._lock:
                    self._check(prepared['generation'], True, {'opening'})
                    self._state = 'awaiting_user'
            except Exception:
                self._fail_current(prepared['generation'], driver)
                raise SessionError('SOURCE_LOGIN_REQUIRED') from None
        elif state not in {'awaiting_user', 'list_ready', 'preview_ready'} or not scope or scope['year'] != 2026:
            raise SessionError('SOURCE_LOGIN_REQUIRED')
        try:
            return self.discover(self.status()['generation'], True)
        except SessionError:
            # An expired Smecel session redirects the list to the login page.
            if credential is None: raise
        self.sign_in(credential)
        return self.discover(self.status()['generation'], True)

    def operational_capture(self, class_id):
        generation = self.status()['generation']
        return self.capture_selected(generation, class_id, True, _operational=True)['preview']

    def operational_schedule(self):
        """The school's weekly grid, read in the same verified session as the class list
        (owner decision 22/10/2026). Validated here; a failure never touches the session state."""
        from .class_schedule import schedule_from_observation
        with self._lock:
            driver, state = self._driver, self._state
        if driver is None or state not in {'list_ready', 'preview_ready'}:
            raise SessionError('SOURCE_LOGIN_REQUIRED')
        try:
            return schedule_from_observation(driver.schedule())
        except Exception:
            raise SessionError('SOURCE_READ_FAILED') from None

    def preserve_and_close(self, storage):
        with self._lock: driver = self._driver
        if driver is not None:
            try: storage.save_session(driver.export_state())
            finally: self.close()

    def remember_if_ready(self, storage):
        with self._lock:
            driver = self._driver if self._state in {'list_ready', 'preview_ready'} else None
        if driver is not None: storage.save_session(driver.export_state())

    def prepare(self, class_id, year):
        url = source_url(class_id, year)  # Validate before replacing any active session.
        self.close()
        with self._lock:
            if self._state != "closed" or self._driver is not None:
                raise SessionError("A sessão anterior ainda está sendo encerrada. Aguarde e tente novamente.")
            self._scope = {"class_id": class_id, "year": year, "url": url}
            self._mode = "annual"
            self._state = "prepared"
            return self._status()

    def _check(self, generation, confirmed, states):
        if type(confirmed) is not bool or not confirmed:
            raise SessionError("Confirme esta etapa e o destino local antes de continuar.")
        if type(generation) is not int or generation != self._generation or self._state not in states:
            raise SessionError("A sessão mudou. Prepare e confira a turma novamente.")

    def open(self, generation, confirmed, can_sign_in=False):
        with self._lock:
            self._check(generation, confirmed, {"prepared"})
            self._state = "opening"
            try:
                driver = self._new_driver(can_sign_in)
            except Exception:
                self._state = "prepared"
                raise SessionError("Não foi possível preparar o navegador isolado.") from None
            self._driver = driver
            url = self._scope["url"]
        try:
            driver.open(url)
            with self._lock:
                self._check(generation, True, {"opening"})
                self._state = "awaiting_user"
                return self._status()
        except Exception:
            self._fail_current(generation, driver)
            raise SessionError("Não foi possível abrir a sessão isolada. Confira se o Microsoft Edge está instalado e prepare novamente.") from None

    def capture(self, generation, confirmed):
        with self._lock:
            self._check(generation, confirmed, {"awaiting_user", "preview_ready"})
            self._state = "capturing"
            driver, scope = self._driver, dict(self._scope)
        try:
            result = captured_preview(driver.capture(), scope["class_id"], scope["year"])
            with self._lock:
                self._check(generation, True, {"capturing"})
                self._state = "preview_ready"
                return {"session": self._status(), "preview": result}
        except SessionError:
            with self._lock:
                if generation == self._generation and self._state == "capturing":
                    self._state = "awaiting_user"
            raise
        except Exception:
            self._fail_current(generation, driver)
            raise SessionError("A sessão deixou de responder. Feche-a e prepare novamente; nenhum resultado foi mantido.") from None

    def _fail_current(self, generation, driver):
        driver.close()
        with self._lock:
            if generation == self._generation:
                self._generation += 1
                self._driver = None
                self._scope = None
                self._state = "closed"

    def close(self):
        with self._lock:
            if self._state == "closing":
                raise SessionError("O encerramento já está em andamento. Aguarde.")
            self._generation += 1
            driver = self._driver
            self._state, self._scope = "closing", None
            self._catalog = None
        if driver is not None:
            try:
                driver.close()
            except Exception:
                with self._lock:
                    self._state = "closed"
                # Keep the owned driver for cleanup retries; never silently
                # replace a session whose temporary files could not be removed.
                raise SessionError("A sessão foi interrompida, mas a limpeza não terminou. Encerre novamente antes de preparar outra sessão.") from None
        with self._lock:
            self._driver = None
            self._state = "closed"
        return self.status()
