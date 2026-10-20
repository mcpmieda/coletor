"""Deterministic fox animation contract, with no desktop or service side effects.

Importing this module never creates threads, windows, files, or network requests.
The caller supplies actual state. Animation never infers collection or sync success.
"""
from dataclasses import dataclass
from enum import StrEnum
import math
from pathlib import Path
import threading
import time
from typing import Callable, Protocol

MIN_FRAME_INTERVAL = 0.6
APP_TITLE = "Coletor de Frequência"
DEFAULT_ASSET_DIRECTORY = Path(__file__).resolve().parents[1] / "assets" / "fox-icons"


class TrayState(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    PAUSED = "paused"
    ERROR = "error"


@dataclass(frozen=True)
class AnimationPolicy:
    enabled: bool = True
    reduced_motion: bool = False
    frame_interval: float = MIN_FRAME_INTERVAL

    def __post_init__(self):
        if (not math.isfinite(self.frame_interval)
                or not MIN_FRAME_INTERVAL <= self.frame_interval <= 60):
            raise ValueError("O intervalo dos quadros deve ficar entre 0,6 e 60 segundos.")
        if type(self.enabled) is not bool or type(self.reduced_motion) is not bool:
            raise TypeError("As preferências de movimento devem ser booleanas.")

    @property
    def animated(self) -> bool:
        return self.enabled and not self.reduced_motion


# A lively fox beside the clock, like the Atualizador's dragon: some gesture on
# almost every 600 ms beat (blinks, ear droops on either or both sides, a nod),
# never more than 1.2 s at rest. Frames come from scripts/make_fox_gestures.py.
IDLE_SEQUENCE = (
    "fox-idle", "fox-idle", "fox-blink", "fox-idle", "fox-ear", "fox-idle",
    "fox-ear", "fox-idle", "fox-ear-right", "fox-idle", "fox-ear-right", "fox-idle",
    "fox-idle", "fox-blink", "fox-idle", "fox-blink", "fox-idle", "fox-ears",
    "fox-ears", "fox-idle", "fox-bob", "fox-idle", "fox-bob", "fox-idle",
    "fox-idle", "fox-ear", "fox-ear-right", "fox-ear", "fox-ear-right", "fox-idle",
    "fox-blink",
)
WORKING_SEQUENCE = tuple(f"fox-working-{index}" for index in range(1, 5))
STATIC_FRAMES = {
    TrayState.IDLE: "fox-idle", TrayState.WORKING: "fox-working-1",
    TrayState.PAUSED: "fox-paused", TrayState.ERROR: "fox-error",
}
STATE_LABELS = {
    TrayState.IDLE: "Aguardando", TrayState.WORKING: "Em andamento",
    TrayState.PAUSED: "Pausado", TrayState.ERROR: "Requer atenção",
}
# Symbols must be drawn into the ICO; color alone is not the state indicator.
STATE_BADGES = {
    TrayState.IDLE: "none", TrayState.WORKING: "progress",
    TrayState.PAUSED: "pause", TrayState.ERROR: "exclamation",
}
FRAME_KEYS = tuple(sorted(set(IDLE_SEQUENCE) | set(WORKING_SEQUENCE) | set(STATIC_FRAMES.values())))


def icon_paths(directory: Path = DEFAULT_ASSET_DIRECTORY) -> dict[str, Path]:
    """Return the bounded local asset manifest. Does not read or generate any file."""
    return {key: Path(directory) / f"{key}.ico" for key in FRAME_KEYS}


def resolve_icon_paths(directory: Path = DEFAULT_ASSET_DIRECTORY) -> dict[str, Path]:
    """Only four state bases are required; optional motion frames fall back safely."""
    paths = icon_paths(directory)
    bases = set(STATIC_FRAMES.values())
    missing = [paths[key].name for key in sorted(bases) if not paths[key].is_file()]
    if missing:
        raise FileNotFoundError("Faltam ícones-base locais da raposa: " + ", ".join(missing))
    return {
        key: path if path.is_file() else paths[
            "fox-working-1" if key in WORKING_SEQUENCE else "fox-idle"]
        for key, path in paths.items()
    }


def tooltip_for(state: TrayState, detail: str = "") -> str:
    """127 UTF-16 code units plus NUL fit Windows' 128-WCHAR tooltip buffer."""
    clean = " ".join("".join(c if c.isprintable() else " " for c in detail).split())
    text = (f"{APP_TITLE} · Modo de teste · Coleta desligada · {STATE_LABELS[state]}"
            + (f" · {clean}" if clean else ""))
    return text.encode("utf-16-le")[:254].decode("utf-16-le", errors="ignore")


@dataclass(frozen=True)
class TrayPresentation:
    state: TrayState
    frame_key: str
    badge: str
    tooltip: str


class AnimationController:
    """Thread-safe state and monotonic-time sampling; no timers or background work.

    Late ticks skip obsolete frames instead of replaying a burst. Only state or
    preference changes can force a visual update before the 0.6-second cadence.
    Repeating the same state or changing only its detail never restarts animation.
    """

    def __init__(self, policy: AnimationPolicy | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._policy = AnimationPolicy() if policy is None else policy
        if not isinstance(self._policy, AnimationPolicy):
            raise TypeError("Informe uma AnimationPolicy válida.")
        self._state = TrayState.IDLE
        self._detail = ""
        self._frame_sampled_at = clock()
        self._tick = 0

    @property
    def policy(self) -> AnimationPolicy:
        with self._lock:
            return self._policy

    def set_state(self, state: TrayState | str, detail: str = "") -> bool:
        state = TrayState(state)  # Fail closed for unknown operational states.
        if not isinstance(detail, str):
            raise TypeError("A descrição do estado deve ser texto.")
        with self._lock:
            changed = (self._state, self._detail) != (state, detail)
            if state != self._state:
                self._frame_sampled_at = self._clock()
                self._tick = 0
            self._state, self._detail = state, detail
            return changed

    def set_policy(self, policy: AnimationPolicy) -> bool:
        if not isinstance(policy, AnimationPolicy):
            raise TypeError("Informe uma AnimationPolicy válida.")
        with self._lock:
            if policy == self._policy:
                return False
            self._policy = policy
            self._frame_sampled_at = self._clock()
            self._tick = 0
            return True

    def snapshot(self) -> TrayPresentation:
        with self._lock:
            frame = STATIC_FRAMES[self._state]
            if self._policy.animated:
                sequence = {TrayState.IDLE: IDLE_SEQUENCE,
                            TrayState.WORKING: WORKING_SEQUENCE}.get(self._state)
                if sequence:
                    now = self._clock()
                    elapsed = max(0.0, now - self._frame_sampled_at)
                    # Gate by the last sampled frame, not a fixed epoch. Frequent
                    # tooltip refreshes cannot squeeze two frames around a boundary.
                    if elapsed + 1e-9 >= self._policy.frame_interval:
                        self._tick += int((elapsed + 1e-9) / self._policy.frame_interval)
                        self._frame_sampled_at = now
                    frame = sequence[self._tick % len(sequence)]
            return TrayPresentation(self._state, frame, STATE_BADGES[self._state],
                                    tooltip_for(self._state, self._detail))


class TraySink(Protocol):
    """Small seam for a native Shell_NotifyIcon backend and Linux test doubles."""
    def add(self, presentation: TrayPresentation) -> None: ...
    def modify(self, presentation: TrayPresentation) -> None: ...
    def remove(self) -> None: ...


class TrayPresenter:
    """Only call from the native tray thread; controller updates may be concurrent."""

    def __init__(self, controller: AnimationController, sink: TraySink):
        self.controller, self.sink = controller, sink
        self._last: TrayPresentation | None = None
        self._registered = False

    def update(self) -> bool:
        current = self.controller.snapshot()
        if not self._registered:
            self.sink.add(current)
            self._registered = True
        elif current != self._last:
            try:
                self.sink.modify(current)
            except Exception:
                # The shell may have restarted before its broadcast was handled.
                # Remove best-effort to avoid duplicate IDs, then retry ADD later.
                try:
                    self.sink.remove()
                except Exception:
                    pass
                self._registered = False
                raise
        else:
            return False
        self._last = current
        return True

    def taskbar_created(self) -> None:
        # Explorer discards every icon; keep the current semantic state and frame.
        self._registered = False
        self._last = None
        self.update()

    def close(self) -> None:
        if self._registered:
            try:
                self.sink.remove()
            finally:
                self._registered = False
                self._last = None
