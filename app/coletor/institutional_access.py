"""Fail-closed access gate; production transport/policy requires backend approval.

This module never treats the current /api/me identity response as a collector
authorization or revocation receipt. No provider is installed by default.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
from typing import Callable, Protocol, TypeVar

OFFICIAL_ORIGIN = "https://admin.escolaieda.com"
OFFICIAL_LOGIN_URL = OFFICIAL_ORIGIN + "/auth/login"
# Proposed contract, not an assertion that this route exists in production.
PROPOSED_ACCESS_URL = OFFICIAL_ORIGIN + "/api/frequency-collector/access"
PROPOSED_CAPABILITY = "frequency.collector.use"
MAX_RESPONSE_BYTES = 8192
T = TypeVar("T")


class AccessDenied(Exception):
    def __init__(self, code="ACCESS_REQUIRED"):
        self.code = code
        super().__init__("Entre no Ecossistema com uma conta autorizada para usar o coletor.")


@dataclass(frozen=True)
class OnlineResponse:
    """Only a Python transport may construct this; never accept it from JS."""
    status: int
    url: str
    body: bytes


class AccessProvider(Protocol):
    def verify_online(self) -> OnlineResponse: ...
    def open_official_login(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class Authorization:
    identity_key: str
    expires_at: float


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise AccessDenied("INVALID_ACCESS_RESPONSE")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.timestamp()
    except (ValueError, OverflowError):
        raise AccessDenied("INVALID_ACCESS_RESPONSE") from None


def validate_authorization(response, now):
    import json
    if (not isinstance(response, OnlineResponse) or response.status != 200
            or response.url != PROPOSED_ACCESS_URL or not isinstance(response.body, bytes)
            or len(response.body) > MAX_RESPONSE_BYTES):
        raise AccessDenied()
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        body = json.loads(response.body, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise AccessDenied("INVALID_ACCESS_RESPONSE") from None
    if (not isinstance(body, dict)
            or set(body) != {"contractVersion", "authenticated", "authorized", "capability",
                             "identityKey", "expiresAt", "checkedAt", "revocationChecked",
                             "directoryCheckedAt", "directoryValidUntil"}
            or type(body["contractVersion"]) is not int or body["contractVersion"] != 2
            or body["authenticated"] is not True or body["authorized"] is not True
            or body["revocationChecked"] is not True
            or body["capability"] != PROPOSED_CAPABILITY):
        raise AccessDenied()
    identity = body["identityKey"]
    if not isinstance(identity, str) or not 1 <= len(identity) <= 160 or not identity.isascii() or any(ord(c) < 33 for c in identity):
        raise AccessDenied("INVALID_ACCESS_RESPONSE")
    expiry, checked = _timestamp(body["expiresAt"]), _timestamp(body["checkedAt"])
    directory_checked = _timestamp(body["directoryCheckedAt"])
    directory_until = _timestamp(body["directoryValidUntil"])
    if expiry <= now or checked > now + 5 or now - checked > 10 or checked >= expiry:
        raise AccessDenied("ACCESS_EXPIRED")
    if (directory_checked > now + 5 or directory_until <= now
            or directory_until - directory_checked != 300
            or expiry > directory_until):
        raise AccessDenied("DIRECTORY_ACCESS_EXPIRED")
    return Authorization(identity, expiry)


class InstitutionalAccess:
    def __init__(self, provider=None, *, clock=time.time, on_locked=lambda: None):
        self._provider = provider
        self._clock = clock
        self._on_locked = on_locked
        self._lock = threading.RLock()
        self._generation = 0
        self._cleanup_pending = False

    def _verify(self, generation):
        try:
            if self._cleanup_pending:
                raise AccessDenied("ACCESS_CLEANUP_PENDING")
            if self._provider is None:
                raise AccessDenied("ACCESS_NOT_CONFIGURED")
            proof = validate_authorization(self._provider.verify_online(), self._clock())
            with self._lock:
                if generation != self._generation:
                    raise AccessDenied()
            return proof
        except AccessDenied:
            self._invalidate()
            raise
        except Exception:
            self._invalidate()
            raise AccessDenied("ACCESS_UNAVAILABLE") from None

    def _invalidate(self):
        with self._lock:
            self._generation += 1
        try:
            self._on_locked()
        except Exception:
            self._cleanup_pending = True

    def run(self, work: Callable[[], T]) -> T:
        with self._lock:
            generation = self._generation
        before = self._verify(generation)
        try:
            result = work()
        except Exception:
            self._verify(generation)
            raise
        after = self._verify(generation)
        if before.identity_key != after.identity_key:
            self._invalidate()
            raise AccessDenied()
        return result

    def status(self):
        with self._lock:
            generation = self._generation
        try:
            self._verify(generation)
            return {"authenticated": True, "authorized": True}
        except AccessDenied as error:
            return {"authenticated": False, "authorized": False, "code": error.code}

    def open_login(self):
        self._invalidate()
        if self._cleanup_pending:
            raise AccessDenied("ACCESS_CLEANUP_PENDING")
        if self._provider is None:
            raise AccessDenied("ACCESS_NOT_CONFIGURED")
        try:
            self._provider.open_official_login()
        except Exception:
            raise AccessDenied("LOGIN_UNAVAILABLE") from None

    def logout(self):
        self._invalidate()
        if self._provider is not None:
            try:
                self._provider.close()
            except Exception:
                self._cleanup_pending = True
                raise AccessDenied("ACCESS_CLEANUP_PENDING") from None
