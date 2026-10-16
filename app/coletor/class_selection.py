"""Local class choices, pending revalidation on every new source session.

Scope comes from the verified listing adapter, never from credentials. This
store has no public generic bridge setter and never authorizes a capture.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile

from .local_settings import LocalSettings, exact_fields

ORIGIN = "https://www.smecel.com.br"
LIST_PATH = "/sistema/escola/turmaListar.php"
MAX_SELECTION_BYTES = 128_000
MAX_CLASSES = 500
NOTICE = "Não foi possível ler a seleção salva. Entre no site e escolha as turmas novamente."


def validate_scope(scope):
    exact_fields(scope, {"origin", "list_path", "year", "context_key"})
    if (scope["origin"] != ORIGIN or scope["list_path"] != LIST_PATH
            or type(scope["year"]) is not int or not 2000 <= scope["year"] <= 2100
            or type(scope["context_key"]) is not str
            or not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", scope["context_key"])):
        raise ValueError("Invalid class selection scope")
    return dict(scope)


def validate_ids(ids):
    if (type(ids) is not list or len(ids) > MAX_CLASSES
            or any(type(value) is not str or not re.fullmatch(r"[1-9][0-9]{0,9}", value) for value in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("Invalid selected classes")
    return sorted(ids, key=int)


def validate_selection(value):
    exact_fields(value, {"schemaVersion", "localRevision", "scope", "selected_class_ids"})
    if (type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
            or type(value["localRevision"]) is not int or not 1 <= value["localRevision"] <= 2**53 - 1):
        raise ValueError("Invalid selection metadata")
    return {"schemaVersion": 1, "localRevision": value["localRevision"],
            "scope": validate_scope(value["scope"]), "selected_class_ids": validate_ids(value["selected_class_ids"])}


def revalidate_choices(saved, fresh_scope, available_ids):
    """Only the fresh current listing can make a saved choice selectable."""
    scope, available = validate_scope(fresh_scope), set(validate_ids(available_ids))
    if saved is None:
        return {"selected_class_ids": [], "unavailable_class_ids": [], "context_matches": True}
    saved = validate_selection(saved)
    if saved["scope"] != scope:
        return {"selected_class_ids": [], "unavailable_class_ids": [], "context_matches": False}
    return {"selected_class_ids": [key for key in saved["selected_class_ids"] if key in available],
            "unavailable_class_ids": [key for key in saved["selected_class_ids"] if key not in available],
            "context_matches": True}


class SelectionConflict(ValueError):
    pass


class ClassSelectionStore:
    def __init__(self, directory=None):
        self._storage = LocalSettings(directory)
        self._directory = self._storage._directory
        self._lock = self._storage._lock
        self._path = self._directory / "class-selection.json"

    def _read(self):
        try:
            with self._path.open("rb") as source:
                raw = source.read(MAX_SELECTION_BYTES + 1)
        except FileNotFoundError:
            return None, ""
        try:
            if len(raw) > MAX_SELECTION_BYTES:
                raise ValueError("Selection too large")
            data = json.loads(raw.decode("utf-8"))
            if type(data) is not dict:
                raise ValueError("Invalid selection object")
            if data.get("schemaVersion") == 1:
                old = validate_selection(data)
                data = {"schemaVersion": 2, "localRevision": old["localRevision"], "profiles": [{"scope": old["scope"], "selected_class_ids": old["selected_class_ids"]}]}
            exact_fields(data, {"schemaVersion", "localRevision", "profiles"})
            if data["schemaVersion"] != 2 or type(data["profiles"]) is not list or not 1 <= len(data["profiles"]) <= 16:
                raise ValueError("Invalid selection profiles")
            profiles, seen = [], set()
            for profile in data["profiles"]:
                exact_fields(profile, {"scope", "selected_class_ids"})
                clean = validate_selection({"schemaVersion": 1, "localRevision": data["localRevision"], **profile})
                key = json.dumps(clean["scope"], sort_keys=True)
                if key in seen:
                    raise ValueError("Duplicate selection scope")
                seen.add(key)
                profiles.append({"scope": clean["scope"], "selected_class_ids": clean["selected_class_ids"]})
            return {"schemaVersion": 2, "localRevision": data["localRevision"], "profiles": profiles}, ""
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return None, NOTICE

    def read(self, scope=None):
        with self._lock:
            data, notice = self._read()
            selection = None
            if data:
                profiles = data["profiles"]
                profile = next((p for p in profiles if p["scope"] == scope), None) if scope else profiles[-1]
                if profile:
                    selection = {"schemaVersion": 1, "localRevision": data["localRevision"], **profile}
            # Reading a persisted choice is never an authentication/availability
            # receipt. The controller must discover the current list first.
            return {"selection": deepcopy(selection), "local_revision": data["localRevision"] if data else 0, "revalidation_required": True, "notice": notice}

    def save(self, scope, ids, expected_revision):
        clean_scope, clean_ids = validate_scope(scope), validate_ids(ids)
        if type(expected_revision) is not int or not 0 <= expected_revision < 2**53 - 1:
            raise ValueError("Invalid selection revision")
        with self._lock, self._storage._process_lock():
            previous, _ = self._read()
            revision = previous["localRevision"] if previous else 0
            if expected_revision != revision:
                raise SelectionConflict("CLASS_SELECTION_REVISION_CONFLICT")
            clean = validate_selection({"schemaVersion": 1, "localRevision": revision + 1,
                                        "scope": clean_scope, "selected_class_ids": clean_ids})
            profiles = [p for p in previous["profiles"] if p["scope"] != clean_scope] if previous else []
            if len(profiles) >= 16:
                raise ValueError("Too many selection contexts; no previous choice was removed")
            profiles.append({"scope": clean_scope, "selected_class_ids": clean_ids})
            data = {"schemaVersion": 2, "localRevision": revision + 1, "profiles": profiles}
            payload = (json.dumps(data, separators=(",", ":")) + "\n").encode("utf-8")
            if len(payload) > MAX_SELECTION_BYTES:
                raise ValueError("Selection too large")
            descriptor, temporary = tempfile.mkstemp(prefix=".class-selection-", suffix=".tmp", dir=self._directory)
            try:
                with os.fdopen(descriptor, "wb") as target:
                    target.write(payload)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temporary, self._path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return deepcopy(clean)
