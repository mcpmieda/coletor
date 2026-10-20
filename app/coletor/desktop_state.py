"""In-memory desktop activity; no scheduler, student data, IO or polling."""
import threading
from .local_settings import validate_fox
ACTIVITIES = {"idle", "reading", "error"}


class DesktopState:
    def __init__(self, fox, reduced_motion=True):
        self._lock = threading.RLock()
        self._fox = validate_fox(fox)
        self._ui_activity = "idle"
        self._reads = 0
        # Until the window reports its media query: static unless the caller knows better.
        self._reduced = reduced_motion is not False
        self._changed = lambda: None

    def snapshot(self):
        with self._lock:
            return {"activity": "reading" if self._reads else self._ui_activity,
                    "fox": dict(self._fox), "reduced_motion": self._reduced}

    def set_context(self, activity, reduced_motion):
        if type(activity) is not str or activity not in ACTIVITIES or type(reduced_motion) is not bool:
            raise ValueError("Invalid desktop context")
        with self._lock:
            changed = (activity, reduced_motion) != (self._ui_activity, self._reduced)
            self._ui_activity, self._reduced = activity, reduced_motion
        if changed: self._changed()

    def set_fox(self, fox):
        clean = validate_fox(fox)
        with self._lock:
            changed = clean != self._fox
            self._fox = clean
        if changed: self._changed()

    def begin_read(self):
        with self._lock: self._reads += 1
        self._changed()

    def end_read(self, error=False):
        with self._lock:
            self._reads = max(0, self._reads - 1)
            if not self._reads: self._ui_activity = "error" if error else "idle"
        self._changed()
