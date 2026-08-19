from __future__ import annotations

import time
from typing import Callable


class PresenceDetectionWindow:
    """Keep vision active briefly after the PIR sensor no longer sees motion."""

    def __init__(
        self,
        *,
        grace_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.grace_seconds = max(0.0, grace_seconds)
        self._monotonic = monotonic
        self._active_until: float | None = None

    def observe(self, presence_detected: bool) -> bool:
        now = self._monotonic()
        if presence_detected:
            self._active_until = now + self.grace_seconds

        if self._active_until is None:
            return False
        if now <= self._active_until:
            return True

        self._active_until = None
        return False

    def reset(self) -> None:
        self._active_until = None
