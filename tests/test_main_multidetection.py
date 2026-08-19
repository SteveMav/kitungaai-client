from __future__ import annotations

import logging
import time
import unittest
from types import SimpleNamespace

from api_client import ApiResult
from deduplication import ProductDeduplicator
from iot_state import LocalDeviceState
from main import _handle_active_session


class _Api:
    def __init__(self) -> None:
        self.sent = []

    def send_detection(self, basket_id, label, confidence, *, detection_id=None):
        self.sent.append((basket_id, label, confidence, detection_id))
        return ApiResult(ok=True, status="PRODUCT_ADDED")


class _Hardware:
    def __init__(self) -> None:
        self.shown = []
        self.beeps = 0

    def presence_detected(self):
        return True

    def apply_presence(self, _presence):
        pass

    def show_detection(self, label, confidence):
        self.shown.append((label, confidence))

    def beep_detection(self):
        self.beeps += 1


class _Preview:
    def __init__(self) -> None:
        self.calls = []

    def update(self, **kwargs):
        self.calls.append(kwargs)


class MultiDetectionFlowTest(unittest.TestCase):
    def test_presence_sends_each_stable_visible_object_once(self) -> None:
        state = LocalDeviceState(device_id="KITUNGA-PI-001")
        state.start_session(basket_id="basket-1", customer={"display_name": "Client"})
        api = _Api()
        hardware = _Hardware()
        preview = _Preview()
        deduplicator = ProductDeduplicator(
            confidence_threshold=0.70,
            stability_frames=1,
            cooldown_seconds=0,
            disappear_frames=2,
        )
        args = SimpleNamespace(
            simulate_detection="ESP32,Arduino,ESP32",
            simulate_confidence=0.95,
            no_send=False,
            basket_poll_interval=10_000,
        )

        _handle_active_session(
            args=args,
            api=api,
            detector=None,
            camera=None,
            state=state,
            hardware=hardware,
            preview=preview,
            deduplicator=deduplicator,
            last_status_poll=time.monotonic(),
            logger=logging.getLogger(__name__),
        )
        _handle_active_session(
            args=args,
            api=api,
            detector=None,
            camera=None,
            state=state,
            hardware=hardware,
            preview=preview,
            deduplicator=deduplicator,
            last_status_poll=time.monotonic(),
            logger=logging.getLogger(__name__),
        )

        self.assertEqual([entry[1] for entry in api.sent], ["ESP32", "Arduino", "ESP32"])
        self.assertEqual(len({entry[3] for entry in api.sent}), 3)
        self.assertEqual(hardware.shown, [("ESP32", 0.95), ("Arduino", 0.95), ("ESP32", 0.95)])
        self.assertEqual(hardware.beeps, 3)
        self.assertEqual(len(preview.calls[0]["detections"]), 3)


if __name__ == "__main__":
    unittest.main()
