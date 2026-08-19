from __future__ import annotations

import unittest

from presence import PresenceDetectionWindow


class PresenceDetectionWindowTest(unittest.TestCase):
    def test_presence_extends_the_detection_window(self) -> None:
        clock = [0.0]
        window = PresenceDetectionWindow(
            grace_seconds=3.0,
            monotonic=lambda: clock[0],
        )

        self.assertFalse(window.observe(False))
        self.assertTrue(window.observe(True))

        clock[0] = 2.5
        self.assertTrue(window.observe(False))

        clock[0] = 2.9
        self.assertTrue(window.observe(True))

        clock[0] = 5.8
        self.assertTrue(window.observe(False))

        clock[0] = 6.0
        self.assertFalse(window.observe(False))

    def test_reset_stops_the_window_immediately(self) -> None:
        window = PresenceDetectionWindow(grace_seconds=3.0)
        self.assertTrue(window.observe(True))
        window.reset()
        self.assertFalse(window.observe(False))


if __name__ == "__main__":
    unittest.main()
