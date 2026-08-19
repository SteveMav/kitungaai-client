from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from detector import DetectionResult


@dataclass(frozen=True)
class StableDetection:
    label: str
    confidence: float


@dataclass
class _LockState:
    missing_frames: int = 0


class ProductDeduplicator:
    def __init__(
        self,
        *,
        confidence_threshold: float,
        stability_frames: int,
        cooldown_seconds: float,
        disappear_frames: int,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.stability_frames = max(1, stability_frames)
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self.disappear_frames = max(1, disappear_frames)
        self._monotonic = monotonic
        self._candidate_label: str | None = None
        self._candidate_count = 0
        self._locked_labels: dict[str, _LockState] = {}
        self._last_attempt_at: dict[str, float] = {}
        self._last_accepted_at: dict[str, float] = {}

    def observe(self, result: DetectionResult) -> StableDetection | None:
        visible_label = self._visible_label(result)
        self._update_locks(visible_label)

        if visible_label is None:
            self._candidate_label = None
            self._candidate_count = 0
            return None

        if visible_label in self._locked_labels:
            return None

        if visible_label != self._candidate_label:
            self._candidate_label = visible_label
            self._candidate_count = 1
        else:
            self._candidate_count += 1

        if self._candidate_count < self.stability_frames:
            return None

        if self._cooldown_active(visible_label):
            return None

        self._last_attempt_at[visible_label] = self._monotonic()
        return StableDetection(label=visible_label, confidence=result.confidence)

    def mark_accepted(self, label: str) -> None:
        self._locked_labels[label] = _LockState(missing_frames=0)
        self._last_accepted_at[label] = self._monotonic()

    def reset(self) -> None:
        self._candidate_label = None
        self._candidate_count = 0
        self._locked_labels.clear()
        self._last_attempt_at.clear()
        self._last_accepted_at.clear()

    def _visible_label(self, result: DetectionResult) -> str | None:
        if not result.found or result.label is None:
            return None
        if result.confidence < self.confidence_threshold:
            return None
        return result.label

    def _update_locks(self, visible_label: str | None) -> None:
        for label in list(self._locked_labels):
            lock = self._locked_labels[label]
            if label == visible_label:
                lock.missing_frames = 0
                continue

            lock.missing_frames += 1
            if lock.missing_frames >= self.disappear_frames:
                del self._locked_labels[label]

    def _cooldown_active(self, label: str) -> bool:
        last_time = self._last_accepted_at.get(label)
        if last_time is None:
            last_time = self._last_attempt_at.get(label)
        if last_time is None:
            return False
        return self._monotonic() - last_time < self.cooldown_seconds
