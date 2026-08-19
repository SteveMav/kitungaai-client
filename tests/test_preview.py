from __future__ import annotations

import unittest

from detector import DetectionResult
from iot_state import LocalDeviceState
from preview import PreviewServer


class PreviewServerTest(unittest.TestCase):
    def test_update_exposes_visible_yolo_detections_to_the_web_view(self) -> None:
        state = LocalDeviceState(device_id="KITUNGA-PI-001")
        state.start_session(customer={"display_name": "Client"})
        state.mark_detection(label="Objet non repertorie : Film-Capacitor", confidence=0.58)
        preview = PreviewServer()

        preview.update(
            frame=None,
            state=state,
            detections=(
                DetectionResult(label="Film-Capacitor", confidence=0.58),
                DetectionResult(label=None, confidence=0.0),
            ),
            presence_detected=True,
            detection_active=True,
        )

        self.assertEqual(preview._status["visible_detections"], 1)
        self.assertEqual(
            preview._status["detections"],
            [{"label": "Film-Capacitor", "confidence": 0.58}],
        )
        self.assertEqual(preview._status["last_label"], "Objet non repertorie : Film-Capacitor")


if __name__ == "__main__":
    unittest.main()
