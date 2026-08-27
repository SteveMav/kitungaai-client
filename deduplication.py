from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable

from detector import DetectionResult


@dataclass(frozen=True)
class StableDetection:
    track_id: str
    label: str
    confidence: float
    bbox_xyxy: tuple[int, int, int, int] | None


@dataclass
class _TrackedDetection:
    track_id: str
    label: str
    bbox_xyxy: tuple[int, int, int, int] | None
    confidence: float
    stable_frames: int
    missing_frames: int = 0
    accepted: bool = False
    last_attempt_at: float | None = None


class ProductDeduplicator:
    def __init__(
        self,
        *,
        confidence_threshold: float,
        stability_frames: int,
        cooldown_seconds: float,
        disappear_frames: int,
        track_iou_threshold: float = 0.30,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.stability_frames = max(1, stability_frames)
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self.disappear_frames = max(1, disappear_frames)
        self.track_iou_threshold = min(1.0, max(0.0, track_iou_threshold))
        self._monotonic = monotonic
        self._tracks: dict[str, _TrackedDetection] = {}
        self._pending_removals: dict[str, StableDetection] = {}

    def observe(self, results: Iterable[DetectionResult]) -> tuple[StableDetection, ...]:
        """Return every independently stable object visible in the current frame.

        An accepted object remains locked to its physical track until it has
        disappeared for ``disappear_frames``. This allows two objects carrying
        the same label to be added once each without re-adding them on every
        camera frame.
        """
        visible = tuple(result for result in results if result.found and result.label)
        assignments = self._match_tracks(visible)
        matched_track_ids = set(assignments.values())
        now = self._monotonic()

        for detection_index, track_id in assignments.items():
            self._update_track(self._tracks[track_id], visible[detection_index])

        for detection_index, detection in enumerate(visible):
            if detection_index not in assignments:
                track = _TrackedDetection(
                    track_id=str(uuid.uuid4()),
                    label=detection.label or "unknown",
                    bbox_xyxy=detection.bbox_xyxy,
                    confidence=detection.confidence,
                    stable_frames=1 if self._is_confident(detection) else 0,
                )
                self._tracks[track.track_id] = track
                matched_track_ids.add(track.track_id)

        for track_id, track in list(self._tracks.items()):
            if track_id in matched_track_ids:
                continue
            track.missing_frames += 1
            track.stable_frames = 0
            if track.missing_frames >= self.disappear_frames:
                if track.accepted:
                    self._pending_removals[track_id] = StableDetection(
                        track_id=track.track_id,
                        label=track.label,
                        confidence=track.confidence,
                        bbox_xyxy=track.bbox_xyxy,
                    )
                del self._tracks[track_id]

        candidates = []
        for track in self._tracks.values():
            if track.track_id not in matched_track_ids:
                continue
            if track.accepted or track.stable_frames < self.stability_frames:
                continue
            if self._cooldown_active(track, now):
                continue
            track.last_attempt_at = now
            candidates.append(
                StableDetection(
                    track_id=track.track_id,
                    label=track.label,
                    confidence=track.confidence,
                    bbox_xyxy=track.bbox_xyxy,
                )
            )
        return tuple(candidates)

    def mark_accepted(self, track_id: str) -> None:
        track = self._tracks.get(track_id)
        if track is not None:
            track.accepted = True

    def pending_removals(self) -> tuple[StableDetection, ...]:
        """Return accepted objects whose disappearance still needs to be sent."""
        return tuple(self._pending_removals.values())

    def mark_removal_handled(self, track_id: str) -> None:
        self._pending_removals.pop(track_id, None)

    def reset(self) -> None:
        self._tracks.clear()
        self._pending_removals.clear()

    def _match_tracks(self, visible: tuple[DetectionResult, ...]) -> dict[int, str]:
        possible_matches = []
        for detection_index, detection in enumerate(visible):
            for track in self._tracks.values():
                if detection.label != track.label:
                    continue
                overlap = _bbox_iou(detection.bbox_xyxy, track.bbox_xyxy)
                if overlap is None:
                    # Bounding boxes are always available with YOLO. This
                    # fallback preserves one-object behavior for simulations.
                    overlap = 1.0
                if overlap >= self.track_iou_threshold:
                    possible_matches.append((overlap, detection_index, track.track_id))

        assignments: dict[int, str] = {}
        matched_tracks: set[str] = set()
        for _overlap, detection_index, track_id in sorted(possible_matches, reverse=True):
            if detection_index in assignments or track_id in matched_tracks:
                continue
            assignments[detection_index] = track_id
            matched_tracks.add(track_id)
        return assignments

    def _update_track(self, track: _TrackedDetection, detection: DetectionResult) -> None:
        was_missing = track.missing_frames > 0
        track.bbox_xyxy = detection.bbox_xyxy
        track.confidence = detection.confidence
        track.missing_frames = 0
        if self._is_confident(detection):
            track.stable_frames = 1 if was_missing else track.stable_frames + 1
        else:
            track.stable_frames = 0

    def _is_confident(self, detection: DetectionResult) -> bool:
        return detection.confidence >= self.confidence_threshold

    def _cooldown_active(self, track: _TrackedDetection, now: float) -> bool:
        return (
            track.last_attempt_at is not None
            and now - track.last_attempt_at < self.cooldown_seconds
        )


def _bbox_iou(
    first: tuple[int, int, int, int] | None,
    second: tuple[int, int, int, int] | None,
) -> float | None:
    if first is None or second is None:
        return None

    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    if intersection == 0:
        return 0.0

    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0
