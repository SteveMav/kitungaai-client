from __future__ import annotations

import unittest

from deduplication import ProductDeduplicator
from detector import DetectionResult


def detection(
    label: str,
    bbox: tuple[int, int, int, int],
    confidence: float = 0.95,
) -> DetectionResult:
    return DetectionResult(label=label, confidence=confidence, bbox_xyxy=bbox)


class ProductDeduplicatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = [0.0]
        self.dedup = ProductDeduplicator(
            confidence_threshold=0.70,
            stability_frames=2,
            cooldown_seconds=4.0,
            disappear_frames=2,
            track_iou_threshold=0.30,
            monotonic=lambda: self.now[0],
        )

    def test_stabilizes_every_object_in_a_frame_including_same_label(self) -> None:
        first_frame = (
            detection("ESP32", (20, 20, 120, 120)),
            detection("Arduino", (180, 20, 280, 120)),
            detection("ESP32", (340, 20, 440, 120)),
        )
        moved_frame = (
            detection("ESP32", (24, 22, 124, 122)),
            detection("Arduino", (184, 22, 284, 122)),
            detection("ESP32", (344, 22, 444, 122)),
        )

        self.assertEqual(self.dedup.observe(first_frame), ())
        candidates = self.dedup.observe(moved_frame)

        self.assertEqual(
            [candidate.label for candidate in candidates],
            ["ESP32", "Arduino", "ESP32"],
        )
        self.assertEqual(len({candidate.track_id for candidate in candidates}), 3)
        for candidate in candidates:
            self.dedup.mark_accepted(candidate.track_id)

        self.assertEqual(self.dedup.observe(moved_frame), ())
        self.assertEqual(self.dedup.observe(first_frame), ())

    def test_removed_object_can_be_added_again_after_disappearing(self) -> None:
        both = (
            detection("ESP32", (20, 20, 120, 120)),
            detection("ESP32", (340, 20, 440, 120)),
        )
        only_second = (detection("ESP32", (340, 20, 440, 120)),)

        self.dedup.observe(both)
        accepted = self.dedup.observe(both)
        self.assertEqual(len(accepted), 2)
        for candidate in accepted:
            self.dedup.mark_accepted(candidate.track_id)

        self.assertEqual(self.dedup.observe(only_second), ())
        self.assertEqual(self.dedup.observe(only_second), ())
        self.assertEqual(self.dedup.observe(both), ())

        replacement = self.dedup.observe(both)
        self.assertEqual(len(replacement), 1)
        self.assertEqual(replacement[0].label, "ESP32")

    def test_accepted_object_disappearance_emits_one_pending_removal(self) -> None:
        visible = (detection("ESP32", (20, 20, 120, 120)),)
        self.dedup.observe(visible)
        accepted = self.dedup.observe(visible)
        self.dedup.mark_accepted(accepted[0].track_id)

        self.assertEqual(self.dedup.observe(()), ())
        self.assertEqual(self.dedup.pending_removals(), ())
        self.assertEqual(self.dedup.observe(()), ())

        removals = self.dedup.pending_removals()
        self.assertEqual(len(removals), 1)
        self.assertEqual(removals[0].label, "ESP32")
        self.dedup.mark_removal_handled(removals[0].track_id)
        self.assertEqual(self.dedup.pending_removals(), ())

    def test_low_confidence_does_not_add_or_release_an_accepted_object(self) -> None:
        confident = (detection("ESP32", (20, 20, 120, 120)),)
        low_confidence = (
            detection("ESP32", (22, 22, 122, 122), confidence=0.20),
        )

        self.dedup.observe(confident)
        accepted = self.dedup.observe(confident)
        self.assertEqual(len(accepted), 1)
        self.dedup.mark_accepted(accepted[0].track_id)

        self.assertEqual(self.dedup.observe(low_confidence), ())
        self.assertEqual(self.dedup.observe(low_confidence), ())
        self.assertEqual(self.dedup.observe(confident), ())


if __name__ == "__main__":
    unittest.main()
