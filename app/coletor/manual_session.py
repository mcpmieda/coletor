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


def captured_preview(payload, class_id, year):
    if not isinstance(payload, dict) or not matches_source(payload.get("url", ""), class_id, year):
        raise SessionError("A janela não está no diário da turma e do ano confirmados. Confira o site.")
    if payload.get("password_form"):
        raise SessionError("A página solicita entrada no site. Faça o login na janela separada e confira o diário.")
    html = payload.get("html")
    result = preview(html, class_id, year, "manual")
    snapshot = result["snapshot"]
    permitted = {"CLASS_ID_UNVERIFIED", "ROSTER_COMPLETENESS_UNVERIFIED"}
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
    def __init__(self, driver_factory=None):
        if driver_factory is None:
            from .manual_worker import BrowserWorker
            driver_factory = BrowserWorker
        self._factory = driver_factory
        self._lock = threading.Lock()
        self._generation = 0
        self._driver = None
        self._state = "closed"
        self._scope = None

    def _status(self):
        return {"generation": self._generation, "state": self._state,
                "scope": self._scope, "identity_verified": False,
                "transmission_enabled": False, "notice": NOTICE,
                "cleanup_pending": self._state == "closed" and self._driver is not None}

    def status(self):
        with self._lock:
            return self._status()

    def prepare(self, class_id, year):
        url = source_url(class_id, year)  # Validate before replacing any active session.
        self.close()
        with self._lock:
            if self._state != "closed" or self._driver is not None:
                raise SessionError("A sessão anterior ainda está sendo encerrada. Aguarde e tente novamente.")
            self._scope = {"class_id": class_id, "year": year, "url": url}
            self._state = "prepared"
            return self._status()

    def _check(self, generation, confirmed, states):
        if type(confirmed) is not bool or not confirmed:
            raise SessionError("Confirme esta etapa e o destino local antes de continuar.")
        if type(generation) is not int or generation != self._generation or self._state not in states:
            raise SessionError("A sessão mudou. Prepare e confira a turma novamente.")

    def open(self, generation, confirmed):
        with self._lock:
            self._check(generation, confirmed, {"prepared"})
            self._state = "opening"
            try:
                driver = self._factory()
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
