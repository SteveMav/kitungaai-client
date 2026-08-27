from __future__ import annotations

import logging
import time
import unittest
from types import SimpleNamespace

from api_client import ApiResult
from deduplication import ProductDeduplicator
from iot_state import LocalDeviceState, SessionStatus
from main import _handle_active_session, _handle_waiting_customer, _poll_basket_status
from presence import PresenceDetectionWindow


class _Api:
    def __init__(self, display_labels=None) -> None:
        self.sent = []
        self.actions = []
        self.payment_requests = []
        self.display_labels = display_labels or {}

    def send_detection(self, label, confidence, *, detection_id=None, action="ITEM_ADDED"):
        self.sent.append((label, confidence, detection_id))
        self.actions.append(action)
        return ApiResult(
            ok=True,
            status="PRODUCT_ADDED" if action == "ITEM_ADDED" else "PRODUCT_REMOVED",
            data={
                "display_label": self.display_labels.get(label, label),
                "action": action,
            },
        )

    def confirm_rfid_payment(self, uid):
        self.payment_requests.append(uid)
        return ApiResult(
            ok=True,
            status="PAID",
            data={"reset_command_id": "reset-command"},
        )


class _Hardware:
    def __init__(self) -> None:
        self.shown = []
        self.beeps = 0
        self.payment_successes = 0
        self.checkout_pending = 0
        self.payment_requested = 0
        self.rfid_scans = 0
        self.basket_initializations = 0
        self.enrollment_pending = 0
        self.waiting = 0
        self.presence = True

    def presence_detected(self):
        return self.presence

    def apply_presence(self, _presence):
        pass

    def show_detection(self, label, confidence):
        self.shown.append((label, confidence))

    def beep_detection(self):
        self.beeps += 1

    def show_payment_success(self):
        self.payment_successes += 1

    def show_payment_requested(self):
        self.payment_requested += 1

    def show_rfid_scanning(self):
        self.rfid_scans += 1

    def show_client_identified(self):
        self.basket_initializations += 1

    def show_rfid_enrollment_pending(self):
        self.enrollment_pending += 1

    def show_error(self):
        pass

    def show_waiting(self):
        self.waiting += 1

    def beep_payment_success(self):
        self.beeps += 1

    def show_checkout_pending(self):
        self.checkout_pending += 1

    def beep_error(self):
        self.beeps += 1


class _Rfid:
    def __init__(self, *uids):
        self.uids = list(uids)

    def read_uid(self):
        return self.uids.pop(0) if self.uids else None


class _Preview:
    def __init__(self) -> None:
        self.calls = []

    def update(self, **kwargs):
        self.calls.append(kwargs)


class MultiDetectionFlowTest(unittest.TestCase):
    def test_idle_backend_status_resets_cancelled_local_basket(self) -> None:
        state = LocalDeviceState(device_id="KITUNGA-PI-001")
        state.start_session(customer={"display_name": "Client"})
        state.mock_items = [{"label": "ESP32", "quantity": 1}]
        api = _Api()
        api.get_invoice_status = lambda: ApiResult(ok=True, status="IDLE", data={"status": "IDLE"})
        hardware = _Hardware()
        deduplicator = ProductDeduplicator(
            confidence_threshold=0.70,
            stability_frames=1,
            cooldown_seconds=0,
            disappear_frames=1,
        )
        presence_window = PresenceDetectionWindow(grace_seconds=3.0)
        presence_window.observe(True)

        _poll_basket_status(
            api=api,
            state=state,
            hardware=hardware,
            deduplicator=deduplicator,
            presence_window=presence_window,
            logger=logging.getLogger(__name__),
        )

        self.assertEqual(state.session_status, SessionStatus.WAITING_CUSTOMER)
        self.assertIsNone(state.customer)
        self.assertEqual(state.mock_items, [])
        self.assertEqual(hardware.waiting, 1)
        self.assertFalse(presence_window.observe(False))

    def test_first_rfid_scan_animates_before_initializing_the_basket(self) -> None:
        state = LocalDeviceState(device_id="KITUNGA-PI-001")
        hardware = _Hardware()
        api = _Api()
        api.start_session = lambda uid: ApiResult(
            ok=True,
            status="ACTIVE",
            data={"customer": {"display_name": "Client"}},
        )

        _handle_waiting_customer(
            api=api,
            rfid=_Rfid("04A732B19C"),
            state=state,
            hardware=hardware,
            preview=_Preview(),
            logger=logging.getLogger(__name__),
        )

        self.assertEqual(hardware.rfid_scans, 1)
        self.assertEqual(hardware.basket_initializations, 1)
        self.assertEqual(state.session_status, SessionStatus.ACTIVE)

    def test_unknown_rfid_scan_switches_to_enrollment_feedback(self) -> None:
        state = LocalDeviceState(device_id="KITUNGA-PI-001")
        hardware = _Hardware()
        api = _Api()
        api.start_session = lambda uid: ApiResult(
            ok=True,
            status="RFID_ENROLLMENT_PENDING",
        )

        _handle_waiting_customer(
            api=api,
            rfid=_Rfid("04A732B19C"),
            state=state,
            hardware=hardware,
            preview=_Preview(),
            logger=logging.getLogger(__name__),
        )

        self.assertEqual(hardware.rfid_scans, 1)
        self.assertEqual(hardware.enrollment_pending, 1)
        self.assertEqual(state.session_status, SessionStatus.RFID_ENROLLMENT_PENDING)

    def test_presence_window_sends_each_object_once_then_stops_after_grace_period(self) -> None:
        state = LocalDeviceState(device_id="KITUNGA-PI-001")
        state.start_session(customer={"display_name": "Client"})
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
        clock = [0.0]
        presence_window = PresenceDetectionWindow(
            grace_seconds=3.0,
            monotonic=lambda: clock[0],
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
            presence_window=presence_window,
            last_status_poll=time.monotonic(),
            logger=logging.getLogger(__name__),
        )
        hardware.presence = False
        clock[0] = 2.0
        _handle_active_session(
            args=args,
            api=api,
            detector=None,
            camera=None,
            state=state,
            hardware=hardware,
            preview=preview,
            deduplicator=deduplicator,
            presence_window=presence_window,
            last_status_poll=time.monotonic(),
            logger=logging.getLogger(__name__),
        )
        clock[0] = 3.1
        _handle_active_session(
            args=args,
            api=api,
            detector=None,
            camera=None,
            state=state,
            hardware=hardware,
            preview=preview,
            deduplicator=deduplicator,
            presence_window=presence_window,
            last_status_poll=time.monotonic(),
            logger=logging.getLogger(__name__),
        )

        self.assertEqual([entry[0] for entry in api.sent], ["ESP32", "Arduino", "ESP32"])
        self.assertEqual(len({entry[2] for entry in api.sent}), 3)
        self.assertEqual(hardware.shown, [("ESP32", 0.95), ("Arduino", 0.95), ("ESP32", 0.95)])
        self.assertEqual(hardware.beeps, 3)
        self.assertEqual(len(preview.calls[0]["detections"]), 3)

    def test_backend_display_label_is_used_for_a_catalogued_model_object(self) -> None:
        state = LocalDeviceState(device_id="KITUNGA-PI-001")
        state.start_session(customer={"display_name": "Client"})
        api = _Api({"Arduino-Mega": "Arduino Mega"})
        hardware = _Hardware()
        preview = _Preview()
        deduplicator = ProductDeduplicator(
            confidence_threshold=0.70,
            stability_frames=1,
            cooldown_seconds=0,
            disappear_frames=2,
        )
        args = SimpleNamespace(
            simulate_detection="Arduino-Mega",
            simulate_confidence=0.95,
            no_send=False,
            basket_poll_interval=10_000,
        )
        presence_window = PresenceDetectionWindow(grace_seconds=3.0)

        _handle_active_session(
            args=args,
            api=api,
            detector=None,
            camera=None,
            state=state,
            hardware=hardware,
            preview=preview,
            deduplicator=deduplicator,
            presence_window=presence_window,
            last_status_poll=time.monotonic(),
            logger=logging.getLogger(__name__),
        )

        self.assertEqual(hardware.shown, [("Arduino Mega", 0.95)])
        self.assertTrue(preview.calls[0]["detection_active"])

    def test_disappearing_accepted_object_sends_a_removal_event(self) -> None:
        state = LocalDeviceState(device_id="KITUNGA-PI-001")
        state.start_session(customer={"display_name": "Client"})
        api = _Api()
        hardware = _Hardware()
        deduplicator = ProductDeduplicator(
            confidence_threshold=0.70,
            stability_frames=1,
            cooldown_seconds=0,
            disappear_frames=1,
        )
        args = SimpleNamespace(
            simulate_detection="ESP32",
            simulate_confidence=0.95,
            no_send=False,
            basket_poll_interval=10_000,
        )
        common = {
            "args": args,
            "api": api,
            "detector": None,
            "camera": None,
            "state": state,
            "hardware": hardware,
            "preview": _Preview(),
            "deduplicator": deduplicator,
            "presence_window": PresenceDetectionWindow(grace_seconds=3.0),
            "last_status_poll": time.monotonic(),
            "logger": logging.getLogger(__name__),
        }

        _handle_active_session(**common)
        args.simulate_detection = " "
        _handle_active_session(**common)

        self.assertEqual(api.actions, ["ITEM_ADDED", "ITEM_REMOVED"])
        self.assertEqual([entry[0] for entry in api.sent], ["ESP32", "ESP32"])
        self.assertEqual(deduplicator.pending_removals(), ())

    def test_second_rfid_read_pays_an_active_basket_before_more_detections(self) -> None:
        state = LocalDeviceState(device_id="KITUNGA-PI-001")
        state.start_session(customer={"display_name": "Client"})
        api = _Api()
        hardware = _Hardware()
        preview = _Preview()
        args = SimpleNamespace(
            simulate_detection="ESP32",
            simulate_confidence=0.95,
            no_send=False,
            basket_poll_interval=10_000,
        )

        _handle_active_session(
            args=args,
            api=api,
            rfid=_Rfid("04A732B19C"),
            detector=None,
            camera=None,
            state=state,
            hardware=hardware,
            preview=preview,
            deduplicator=ProductDeduplicator(
                confidence_threshold=0.70,
                stability_frames=1,
                cooldown_seconds=0,
                disappear_frames=2,
            ),
            presence_window=PresenceDetectionWindow(grace_seconds=3.0),
            last_status_poll=time.monotonic(),
            logger=logging.getLogger(__name__),
        )

        self.assertEqual(api.payment_requests, ["04A732B19C"])
        self.assertEqual(state.session_status, SessionStatus.PAYMENT_SUCCESS)
        self.assertEqual(state.reset_command_id, "reset-command")
        self.assertEqual(hardware.payment_requested, 1)
        self.assertEqual(hardware.payment_successes, 1)
        self.assertEqual(api.sent, [])

    def test_second_rfid_read_waits_for_backend_payment_confirmation(self) -> None:
        state = LocalDeviceState(device_id="KITUNGA-PI-001")
        state.start_session(customer={"display_name": "Client"})
        api = _Api()
        api.confirm_rfid_payment = lambda uid: ApiResult(
            ok=True,
            status="PAYMENT_CONFIRMATION_PENDING",
            data={"payment_request_id": "request-id"},
        )
        hardware = _Hardware()

        _handle_active_session(
            args=SimpleNamespace(
                simulate_detection="ESP32",
                simulate_confidence=0.95,
                no_send=False,
                basket_poll_interval=10_000,
            ),
            api=api,
            rfid=_Rfid("04A732B19C"),
            detector=None,
            camera=None,
            state=state,
            hardware=hardware,
            preview=_Preview(),
            deduplicator=ProductDeduplicator(
                confidence_threshold=0.70,
                stability_frames=1,
                cooldown_seconds=0,
                disappear_frames=2,
            ),
            presence_window=PresenceDetectionWindow(grace_seconds=3.0),
            last_status_poll=time.monotonic(),
            logger=logging.getLogger(__name__),
        )

        self.assertEqual(state.session_status, SessionStatus.CHECKOUT_PENDING)
        self.assertEqual(hardware.payment_requested, 1)
        self.assertEqual(hardware.checkout_pending, 1)
        self.assertEqual(hardware.payment_successes, 0)


if __name__ == "__main__":
    unittest.main()
