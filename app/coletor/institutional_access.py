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


# Reads (status/UI polling) may reuse a grant confirmed online this recently.
# Commands never do: run() always waits for a request sent after it started.
STATUS_REUSE_SECONDS = 5.0


class _Flight:
    """One online verification shared by every caller that joins it."""
    def __init__(self, number):
        self.number = number
        self.done = threading.Event()
        self.proof = None
        self.code = None


class InstitutionalAccess:
    def __init__(self, provider=None, *, clock=time.time, on_locked=lambda: None,
                 monotonic=time.monotonic, status_reuse_seconds=STATUS_REUSE_SECONDS):
        self._provider = provider
        self._clock = clock
        self._monotonic = monotonic
        self._status_reuse_seconds = status_reuse_seconds
        self._on_locked = on_locked
        self._lock = threading.RLock()
        self._generation = 0
        self._cleanup_pending = False
        # A failed server/device logout is not cured by closing a browser worker.
        self._logout_cleanup_pending = False
        self._cleanup_operation = threading.RLock()
        # Background polling before initial authorization cannot own a source
        # capture. Cancel workers only when an actual valid grant was observed.
        self._verified_access = False
        self._locked_code = None
        self._flight = None
        self._flights_started = 0
        # (generation, proof, monotonic time) of the last online confirmation.
        self._confirmed = None

    def _fetch(self):
        if self._provider is None:
            raise AccessDenied("ACCESS_NOT_CONFIGURED")
        try:
            return validate_authorization(self._provider.verify_online(), self._clock())
        except AccessDenied:
            raise
        except Exception:
            raise AccessDenied("ACCESS_UNAVAILABLE") from None

    def _online(self, fresh):
        """Coalesce concurrent verifications into one provider request.

        A fresh caller only accepts a request started after it arrived, so its
        answer is never older than a dedicated request would have been.
        """
        with self._lock:
            floor = self._flights_started + 1 if fresh else 0
        while True:
            with self._lock:
                flight, owner = self._flight, False
                if flight is None:
                    self._flights_started += 1
                    flight = self._flight = _Flight(self._flights_started)
                    owner = True
            if owner:
                needs_cleanup = False
                try:
                    flight.proof = self._fetch()
                except AccessDenied as error:
                    flight.code = error.code
                    needs_cleanup = self._fence(error.code)
                finally:
                    with self._lock:
                        self._flight = None
                    # Release joiners before cleanup: on_locked may wait for a
                    # worker that is itself waiting on this verification.
                    flight.done.set()
                if needs_cleanup:
                    self._cleanup()
            else:
                flight.done.wait()
            if flight.number >= floor:
                if flight.code is not None:
                    raise AccessDenied(flight.code)
                return flight.proof

    def _reusable(self, generation):
        with self._lock:
            confirmed = self._confirmed
            if confirmed is None or confirmed[0] != generation:
                return None
            age = self._monotonic() - confirmed[2]
            proof = confirmed[1]
        if 0 <= age <= self._status_reuse_seconds and proof.expires_at > self._clock():
            return proof
        return None

    def _verify(self, generation, reuse=False):
        if self._cleanup_pending:
            self._invalidate("ACCESS_CLEANUP_PENDING")
            raise AccessDenied("ACCESS_CLEANUP_PENDING")
        if reuse:
            proof = self._reusable(generation)
            if proof is not None:
                return proof
        proof = self._online(fresh=not reuse)
        with self._lock:
            current = generation == self._generation
            if current:
                self._verified_access = True
                self._confirmed = (generation, proof, self._monotonic())
        if not current:
            self._invalidate()
            raise AccessDenied()
        return proof

    def _fence(self, code):
        transient = code == 'ACCESS_UNAVAILABLE'
        with self._lock:
            # A concurrent transient heartbeat/status request cannot fence a
            # valid in-flight capture. Its own request still fails closed; the
            # capture must independently pass its final online verification.
            if not transient:
                self._generation += 1
            needs_cleanup = not transient and self._verified_access
            if needs_cleanup:
                self._verified_access = False
            self._locked_code = code
            self._confirmed = None
        return needs_cleanup

    def _cleanup(self):
        # An unauthenticated polling failure must not repeatedly close an
        # idle source, then set ACCESS_CLEANUP_PENDING during first login.
        # A previously verified grant still fences and cancels its work.
        with self._cleanup_operation:
            try:
                self._on_locked()
            except Exception:
                self._cleanup_pending = True

    def _invalidate(self, code='ACCESS_REQUIRED'):
        if self._fence(code):
            self._cleanup()

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
            self._verify(generation, reuse=True)
            return {"authenticated": True, "authorized": True}
        except AccessDenied as error:
            status = {"authenticated": False, "authorized": False, "code": error.code}
            details = getattr(self._provider, "public_status", lambda: {})()
            if isinstance(details, dict) and isinstance(details.get("pairingCode"), str) and len(details["pairingCode"]) == 6 and details["pairingCode"].isascii() and details["pairingCode"].isdigit():
                status["pairingCode"] = details["pairingCode"]
            return status

    def open_login(self):
        # Native status checks or the initial account change may fail while
        # closing a transient source worker. Retry only this non-destructive
        # cleanup; never treat it as proof of device/server revocation.
        with self._cleanup_operation:
            self._invalidate('ACCOUNT_CHANGED')
            if self._cleanup_pending:
                if self._logout_cleanup_pending:
                    raise AccessDenied('ACCESS_CLEANUP_PENDING')
                try:
                    self._on_locked()
                except Exception:
                    raise AccessDenied('ACCESS_CLEANUP_PENDING') from None
                self._cleanup_pending = False
        if self._provider is None:
            raise AccessDenied("ACCESS_NOT_CONFIGURED")
        try:
            self._provider.open_official_login()
        except AccessDenied:
            raise
        except Exception:
            raise AccessDenied("LOGIN_UNAVAILABLE") from None

    def logout(self):
        with self._cleanup_operation:
            self._invalidate('LOGOUT')
            failed = False
            provider_failed = False
            try:
                self._on_locked()
            except Exception:
                failed = True
            if self._provider is not None:
                try:
                    self._provider.close()
                except Exception:
                    failed = provider_failed = True
            self._logout_cleanup_pending = provider_failed
            self._cleanup_pending = failed
            if failed:
                raise AccessDenied("ACCESS_CLEANUP_PENDING") from None

    def shutdown(self):
        release = getattr(self._provider, "release", None)
        if release is not None:
            release()
