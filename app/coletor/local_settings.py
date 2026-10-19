"""Local, non-secret desktop settings; never browser profiles or diary storage."""
from copy import deepcopy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import tempfile
import threading

MAX_BYTES = 16_000
SCHEDULE_FIELDS = {"schemaVersion", "scope", "storageMode", "localRevision", "sharedRevision", "timezone", "rules"}
RULE_FIELDS = {"weekday", "shift", "selected", "times", "reconciliation"}
TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
ZONE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+){1,2}")
RECOVERY_NOTICE = "Não foi possível ler as configurações salvas. Mostramos as sugestões; salve para guardar novamente."


def default_settings():
    return {"schemaVersion": 1, "schedule": None, "theme": "system", "fox": {"version": 1, "show": True, "animate": True},
            # Minimal intervention: collect every class of the school (new ones
            # included) with the isolated Edge hidden, unless the operator opts out.
            "browser": {"visible": False}, "classes": {"mode": "all"},
            # Balloons beside the clock for problems that need a person.
            "notifications": {"show": True}}


def default_settings_without_classes():
    value = default_settings()
    del value["classes"]
    return value


def exact_fields(value, fields):
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid settings schema")


def validate_schedule(value):
    exact_fields(value, SCHEDULE_FIELDS)
    if (type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or value["scope"] != "school"
            or value["storageMode"] != "local-preview" or value["sharedRevision"] is not None
            or type(value["localRevision"]) is not int or not 0 <= value["localRevision"] <= 2**53 - 1):
        raise ValueError("Invalid schedule metadata")
    zone = value["timezone"]
    # Semantic IANA validation also runs in the UI's Intl.DateTimeFormat. Python's
    # embedded Windows runtime has no IANA database; never install one here.
    if type(zone) is not str or len(zone) > 80 or not ZONE.fullmatch(zone):
        raise ValueError("Invalid timezone")
    rules = value["rules"]
    if type(rules) is not list or len(rules) != 14:
        raise ValueError("Invalid schedule rules")
    seen = set()
    for rule in rules:
        exact_fields(rule, RULE_FIELDS)
        if (type(rule["weekday"]) is not int or not 1 <= rule["weekday"] <= 7
                or rule["shift"] not in ("matutino", "vespertino") or type(rule["selected"]) is not bool):
            raise ValueError("Invalid schedule day")
        key = (rule["weekday"], rule["shift"])
        if key in seen:
            raise ValueError("Duplicate schedule day")
        seen.add(key)
        times, final = rule["times"], rule["reconciliation"]
        if (type(times) is not list or len(times) > 16
                or any(type(t) is not str or not TIME.fullmatch(t) for t in times)
                or len(set(times)) != len(times) or (rule["selected"] and not times)):
            raise ValueError("Invalid schedule times")
        if type(final) is not str or (final and (not TIME.fullmatch(final) or any(t >= final for t in times))):
            raise ValueError("Invalid reconciliation")
    clean = deepcopy(value)
    for rule in clean["rules"]:
        rule["times"].sort()
    return clean


def validate_fox(value):
    exact_fields(value, {"version", "show", "animate"})
    if type(value["version"]) is not int or value["version"] != 1 or type(value["show"]) is not bool or type(value["animate"]) is not bool:
        raise ValueError("Invalid fox preferences")
    return dict(value)


def validate_browser(value):
    exact_fields(value, {"visible"})
    if type(value["visible"]) is not bool:
        raise ValueError("Invalid browser preference")
    return dict(value)


def validate_classes(value):
    exact_fields(value, {"mode"})
    if value["mode"] not in ("all", "chosen"):
        raise ValueError("Invalid class preference")
    return dict(value)


def validate_notifications(value):
    exact_fields(value, {"show"})
    if type(value["show"]) is not bool:
        raise ValueError("Invalid notification preference")
    return dict(value)


def validate_settings(value):
    # Files written before browser/classes/notifications existed stay valid with the defaults.
    if type(value) is dict and {"schemaVersion", "schedule", "theme", "fox"} <= set(value):
        value = {**default_settings(), **value}
    exact_fields(value, {"schemaVersion", "schedule", "theme", "fox", "browser", "classes", "notifications"})
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or value["theme"] not in ("system", "light", "dark"):
        raise ValueError("Invalid preferences")
    return {"schemaVersion": 1, "schedule": None if value["schedule"] is None else validate_schedule(value["schedule"]),
            "theme": value["theme"], "fox": validate_fox(value["fox"]),
            "browser": validate_browser(value["browser"]), "classes": validate_classes(value["classes"]),
            "notifications": validate_notifications(value["notifications"])}


def user_settings_directory():
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise OSError("Local user settings directory unavailable")
    return Path(base) / "ColetorFrequenciaSmecel"


class ScheduleConflict(ValueError):
    """The operator must reload before saving an outdated schedule."""


class LocalSettings:
    """Fixed preference JSON and lock sidecar; construction performs no IO."""
    def __init__(self, directory=None):
        self._directory = Path(directory) if directory is not None else user_settings_directory()
        self._path = self._directory / "settings.json"
        self._lock = threading.RLock()
        self._cached, self._cached_stamp = None, None

    @contextmanager
    def _process_lock(self):
        # Persistent sidecar: removing a lock file would create an inode race.
        # The OS releases the byte/flock lock on process exit, including crashes.
        self._directory.mkdir(parents=True, exist_ok=True)
        with (self._directory / "settings.lock").open("a+b") as lock:
            if os.name == "nt":
                import msvcrt
                if lock.tell() == 0:
                    lock.write(b"\0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _had_chosen_classes(self):
        """Installations from before 'Todas as turmas' chose classes by hand:
        an upgrade keeps that choice instead of silently collecting every class."""
        try:
            saved = json.loads((self._directory / "class-selection.json").read_text(encoding="utf-8"))
            return any(isinstance(p, dict) and p.get("selected_class_ids") for p in saved.get("profiles", []))
        except (OSError, ValueError, AttributeError, TypeError):
            return False

    def _upgrade(self, value):
        if isinstance(value, dict) and "classes" not in value and self._had_chosen_classes():
            value = {**value, "classes": {"mode": "chosen"}}
        return value

    def _read(self):
        try:
            with self._path.open("rb") as file:
                raw = file.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return validate_settings(self._upgrade(default_settings_without_classes())), ""
        try:
            if len(raw) > MAX_BYTES:
                raise ValueError("Settings too large")
            return validate_settings(self._upgrade(json.loads(raw.decode("utf-8")))), ""
        except (ValueError, UnicodeError, RecursionError, TypeError):
            # No invalid-content backup or input echo. Replace only after a valid
            # explicit save; never copy arbitrary material from a damaged file.
            return default_settings(), RECOVERY_NOTICE

    def read(self):
        """Parsed once per file version: the tray and status calls read this
        every few seconds, so an unchanged file is not parsed again."""
        with self._lock:
            try:
                stat = self._path.stat()
                stamp = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                stamp = None
            if stamp is None or stamp != self._cached_stamp:
                self._cached = self._read()
                self._cached_stamp = stamp
            settings, notice = self._cached
            return {"settings": deepcopy(settings), "notice": notice}

    def update(self, field, value):
        if field not in {"schedule", "theme", "fox", "browser", "classes", "notifications"}:
            raise ValueError("Unknown preference")
        with self._lock, self._process_lock():
            settings, _ = self._read()  # Preserve unrelated allowed preferences.
            if field == "schedule":
                value = validate_schedule(value)
                revision = settings["schedule"]["localRevision"] if settings["schedule"] else 0
                if value["localRevision"] != revision + 1:
                    raise ScheduleConflict("SCHEDULE_REVISION_CONFLICT")
            settings[field] = value
            clean = validate_settings(settings)
            payload = (json.dumps(clean, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            if len(payload) > MAX_BYTES:
                raise ValueError("Settings too large")
            self._directory.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=self._directory)
            try:
                with os.fdopen(descriptor, "wb") as file:
                    file.write(payload)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self._path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            self._cached_stamp = None  # Same-second writes keep the size: never trust the cache here.
            return deepcopy(clean)

