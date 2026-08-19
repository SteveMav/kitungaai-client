from __future__ import annotations

import unittest

from deduplication import ProductDeduplicator
from detector import DetectionResult


class ProductDeduplicatorTest(unittest.TestCase):
    def test_adds_once_until_disappearance_and_cooldown(self) -> None:
        now = [0.0]
        dedup = ProductDeduplicator(
            confidence_threshold=0.70,
            stability_frames=2,
            cooldown_seconds=4.0,
            disappear_frames=2,
            monotonic=lambda: now[0],
        )
        esp32 = DetectionResult(label="ESP32", confidence=0.95)
        empty = DetectionResult(label=None, confidence=0.0)

        self.assertIsNone(dedup.observe(esp32))
        stable = dedup.observe(esp32)
        self.assertIsNotNone(stable)
        self.assertEqual(stable.label, "ESP32")
        dedup.mark_accepted("ESP32")

        self.assertIsNone(dedup.observe(esp32))
        self.assertIsNone(dedup.observe(esp32))

        self.assertIsNone(dedup.observe(empty))
        self.assertIsNone(dedup.observe(empty))

        now[0] = 5.0
        self.assertIsNone(dedup.observe(esp32))
        stable_again = dedup.observe(esp32)
        self.assertIsNotNone(stable_again)
        self.assertEqual(stable_again.label, "ESP32")

    def test_low_confidence_never_stabilizes(self) -> None:
        dedup = ProductDeduplicator(
            confidence_threshold=0.70,
            stability_frames=1,
            cooldown_seconds=0,
            disappear_frames=1,
        )
        result = DetectionResult(label="ESP32", confidence=0.2)
        self.assertIsNone(dedup.observe(result))


if __name__ == "__main__":
    unittest.main()
