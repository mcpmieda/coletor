"""Local, non-secret desktop settings; never browser profiles or diary storage."""
from copy import deepcopy
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
    return {"schemaVersion": 1, "schedule": None, "theme": "system", "fox": {"version": 1, "show": True, "animate": True}}


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


def validate_settings(value):
    exact_fields(value, {"schemaVersion", "schedule", "theme", "fox"})
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or value["theme"] not in ("system", "light", "dark"):
        raise ValueError("Invalid preferences")
    return {"schemaVersion": 1, "schedule": None if value["schedule"] is None else validate_schedule(value["schedule"]),
            "theme": value["theme"], "fox": validate_fox(value["fox"])}


def user_settings_directory():
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise OSError("Local user settings directory unavailable")
    return Path(base) / "ColetorFrequenciaSmecel"


class LocalSettings:
    """Only this fixed JSON file is used; construction performs no filesystem IO."""
    def __init__(self, directory=None):
        self._directory = Path(directory) if directory is not None else user_settings_directory()
        self._path = self._directory / "settings.json"
        self._lock = threading.RLock()

    def _read(self):
        try:
            with self._path.open("rb") as file:
                raw = file.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return default_settings(), ""
        try:
            if len(raw) > MAX_BYTES:
                raise ValueError("Settings too large")
            return validate_settings(json.loads(raw.decode("utf-8"))), ""
        except (ValueError, UnicodeError, RecursionError, TypeError):
            # No invalid-content backup or input echo. Replace only after a valid
            # explicit save; never copy arbitrary material from a damaged file.
            return default_settings(), RECOVERY_NOTICE

    def read(self):
        with self._lock:
            settings, notice = self._read()
            return {"settings": settings, "notice": notice}

    def update(self, field, value):
        if field not in {"schedule", "theme", "fox"}:
            raise ValueError("Unknown preference")
        with self._lock:
            settings, _ = self._read()  # Preserve unrelated allowed preferences.
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
            return deepcopy(clean)

