from __future__ import annotations

import threading
import time
import unittest

from matrix import (
    BUSINESS_STATES,
    PERSISTENT_STATES,
    TEMPORARY_STATES,
    Max7219Display,
    MatrixDisplay,
    render_frames_ascii,
    state_to_frames,
    text_to_frames,
)
from matrix_animations import PLUS_LARGE, animation_names, get_animation
from hardware import HardwareConfig, HardwareController


class _FakeSpi:
    def __init__(self) -> None:
        self.opened: tuple[int, int] | None = None
        self.mode = None
        self.max_speed_hz = None
        self.transfers: list[list[int]] = []
        self.writer_threads: list[int] = []
        self.concurrent_writes = False
        self._transfer_lock = threading.Lock()
        self.closed = False

    def open(self, bus: int, chip: int) -> None:
        self.opened = (bus, chip)

    def xfer2(self, payload: list[int]) -> None:
        if not self._transfer_lock.acquire(blocking=False):
            self.concurrent_writes = True
            self._transfer_lock.acquire()
        try:
            self.writer_threads.append(threading.get_ident())
            self.transfers.append(payload)
            time.sleep(0.0005)
        finally:
            self._transfer_lock.release()

    def close(self) -> None:
        self.closed = True


class _FakeMatrix:
    def __init__(self) -> None:
        self.states: list[str] = []
        self.events: list[tuple[str, str | None]] = []

    def show_state(self, state: str) -> None:
        self.states.append(state)

    def play_animation(self, state: str, *, resume_state: str | None = None) -> None:
        self.events.append((state, resume_state))

    def show_detection(self, label: str, confidence: float) -> None:
        self.events.append(("PRODUCT_ADDED", "ACTIVE"))


class _FakeSpiWithOpenPath(_FakeSpi):
    def __init__(self) -> None:
        super().__init__()
        self.opened_path: str | None = None

    def open_path(self, device: str) -> None:
        self.opened_path = device


class MatrixTest(unittest.TestCase):
    def test_spidev_without_open_path_uses_open_bus_chip(self) -> None:
        fake = _FakeSpi()
        display = Max7219Display(
            device="/dev/spidev0.0",
            cascaded=2,
            spi_factory=lambda: fake,
        )
        try:
            self.assertEqual(fake.opened, (0, 0))
            display.show_text("OK")
            self.assertTrue(any(len(payload) == 4 for payload in fake.transfers))
        finally:
            display.close()
        self.assertTrue(fake.closed)

    def test_spidev_open_path_and_max7219_register_initialization_are_preserved(self) -> None:
        fake = _FakeSpiWithOpenPath()
        display = Max7219Display(
            device="/dev/spidev0.0",
            intensity=3,
            cascaded=1,
            spi_factory=lambda: fake,
        )
        try:
            self.assertEqual(fake.opened_path, "/dev/spidev0.0")
            self.assertEqual(
                fake.transfers[:5],
                [
                    [0x0F, 0x00],
                    [0x09, 0x00],
                    [0x0B, 0x07],
                    [0x0A, 0x03],
                    [0x0C, 0x01],
                ],
            )
        finally:
            display.close()

    def test_matrix_display_state_uses_fake_spi(self) -> None:
        fake = _FakeSpi()
        display = MatrixDisplay(
            cascaded=1,
            spi_factory=lambda: fake,
        )
        try:
            transfers_before = len(fake.transfers)
            display.show_state("CHECKOUT_PENDING")
            deadline = time.monotonic() + 0.5
            while len(fake.transfers) == transfers_before and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertGreater(len(fake.transfers), transfers_before)
            self.assertEqual(display.current_state, "CHECKOUT_PENDING")
        finally:
            display.close()

    def test_matrix_display_remains_compatible_with_cascaded_modules(self) -> None:
        fake = _FakeSpi()
        display = MatrixDisplay(cascaded=3, spi_factory=lambda: fake)
        fake.transfers.clear()
        try:
            display.show_state("ACTIVE")
            deadline = time.monotonic() + 0.5
            while not fake.transfers and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertTrue(fake.transfers)
            self.assertTrue(all(len(payload) == 6 for payload in fake.transfers))
        finally:
            display.close()

    def test_text_preview_renders_multiple_frames(self) -> None:
        frames = text_to_frames("PAY", 4)
        preview = render_frames_ascii(frames)
        self.assertIn("██", preview)

    def test_single_matrix_states_are_non_empty_unique_frames(self) -> None:
        states = (
            "WAITING_CUSTOMER",
            "ACTIVE",
            "PRODUCT_ADDED",
            "CHECKOUT_PENDING",
            "PAYMENT_SUCCESS",
            "ERROR",
        )
        frames = [state_to_frames(state, 1) for state in states]

        self.assertTrue(all(len(state_frames) == 1 for state_frames in frames))
        flattened = [state_frames[0] for state_frames in frames]
        self.assertTrue(all(any(row for row in frame) for frame in flattened))
        self.assertEqual(len(set(flattened)), len(states))

    def test_all_business_stages_have_valid_animations(self) -> None:
        required_states = {
            "STARTUP",
            "WAITING_CUSTOMER",
            "RFID_SCANNING",
            "RFID_ENROLLMENT_PENDING",
            "BASKET_INITIALIZED",
            "ACTIVE",
            "CLIENT_IDENTIFIED",
            "PRODUCT_ADDED",
            "PAYMENT_REQUESTED",
            "CHECKOUT_PENDING",
            "PAYMENT_SUCCESS",
            "INSUFFICIENT_FUNDS",
            "ERROR",
        }
        self.assertTrue(required_states.issubset(set(animation_names())))
        self.assertEqual(BUSINESS_STATES, set(animation_names()))
        self.assertIn("RFID_ENROLLMENT_PENDING", PERSISTENT_STATES)
        self.assertEqual(
            TEMPORARY_STATES,
            {
                "RFID_SCANNING",
                "CLIENT_IDENTIFIED",
                "PRODUCT_ADDED",
                "PAYMENT_REQUESTED",
                "PAYMENT_SUCCESS",
            },
        )

        for state in required_states:
            with self.subTest(state=state):
                animation = get_animation(state)
                self.assertTrue(animation.steps)
                for step in animation.steps:
                    self.assertEqual(len(step.frame), 8)
                    self.assertTrue(all(0 <= row <= 0xFF for row in step.frame))
                    self.assertGreater(step.duration, 0)

    def test_product_added_shows_a_clear_plus_then_returns_to_active(self) -> None:
        animation = get_animation("PRODUCT_ADDED")
        plus_steps = [step for step in animation.steps if step.frame == PLUS_LARGE]
        self.assertEqual(len(plus_steps), 1)
        self.assertGreaterEqual(plus_steps[0].duration, 0.40)

        display = MatrixDisplay(cascaded=1, spi_factory=_FakeSpi)
        try:
            display.show_state("ACTIVE")
            display.show_detection("ESP32", 0.95)
            self.assertEqual(display.current_state, "PRODUCT_ADDED")
            deadline = time.monotonic() + 1.5
            while display.current_state != "ACTIVE" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(display.current_state, "ACTIVE")
        finally:
            display.close()

    def test_payment_success_is_temporary_but_errors_remain_persistent(self) -> None:
        display = MatrixDisplay(cascaded=1, spi_factory=_FakeSpi)
        try:
            display.show_state("CHECKOUT_PENDING")
            display.show_state("PAYMENT_SUCCESS")
            self.assertEqual(display.current_state, "PAYMENT_SUCCESS")
            deadline = time.monotonic() + 1.8
            while display.current_state != "CHECKOUT_PENDING" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(display.current_state, "CHECKOUT_PENDING")

            display.show_state("ERROR")
            time.sleep(0.85)
            self.assertEqual(display.current_state, "ERROR")
            display.show_state("INSUFFICIENT_FUNDS")
            time.sleep(1.25)
            self.assertEqual(display.current_state, "INSUFFICIENT_FUNDS")
        finally:
            display.close()

    def test_events_are_queued_and_resume_the_persistent_state(self) -> None:
        fake = _FakeSpi()
        display = MatrixDisplay(cascaded=1, spi_factory=lambda: fake)
        try:
            display.show_state("WAITING_CUSTOMER")
            started_at = time.monotonic()
            display.play_animation("RFID_SCANNING")
            display.play_animation("BASKET_INITIALIZED", resume_state="ACTIVE")
            self.assertLess(time.monotonic() - started_at, 0.05)
            self.assertEqual(display.current_state, "RFID_SCANNING")

            deadline = time.monotonic() + 2.0
            while display.current_state != "ACTIVE" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(display.current_state, "ACTIVE")
        finally:
            display.close()

    def test_rfid_events_remain_visible_in_order_before_active(self) -> None:
        display = MatrixDisplay(cascaded=1, spi_factory=_FakeSpi)
        try:
            display.show_state("WAITING_CUSTOMER")
            display.play_animation("RFID_SCANNING")
            display.play_animation("CLIENT_IDENTIFIED")
            display.play_animation("BASKET_INITIALIZED", resume_state="ACTIVE")

            for expected, timeout in (
                ("RFID_SCANNING", 0.2),
                ("CLIENT_IDENTIFIED", 0.8),
                ("BASKET_INITIALIZED", 1.0),
                ("ACTIVE", 1.2),
            ):
                deadline = time.monotonic() + timeout
                while display.current_state != expected and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(display.current_state, expected)
        finally:
            display.close()

    def test_only_worker_thread_writes_spi_after_initialization(self) -> None:
        fake = _FakeSpi()
        display = MatrixDisplay(cascaded=1, spi_factory=lambda: fake)
        fake.writer_threads.clear()
        try:
            calls = (
                lambda: display.show_state("ACTIVE"),
                lambda: display.play_animation("PRODUCT_ADDED", resume_state="ACTIVE"),
                lambda: display.show_text("OK"),
                lambda: display.show_identifier(7),
                display.clear,
            )
            callers = [threading.Thread(target=call) for call in calls]
            for caller in callers:
                caller.start()
            for caller in callers:
                caller.join()

            self.assertTrue(fake.writer_threads)
            self.assertEqual(len(set(fake.writer_threads)), 1)
            self.assertFalse(fake.concurrent_writes)
        finally:
            display.close()

    def test_hardware_controller_maps_each_basket_stage_to_a_visual(self) -> None:
        controller = HardwareController(HardwareConfig(enabled=False))
        matrix = _FakeMatrix()
        controller.matrix = matrix

        controller.show_startup()
        controller.show_rfid_scanning()
        controller.show_rfid_enrollment_pending()
        controller.show_client_identified()
        controller.show_detection("ESP32", 0.95)
        controller.show_payment_requested()
        controller.show_checkout_pending()
        controller.show_insufficient_funds()
        controller.show_payment_success()

        self.assertEqual(
            matrix.states,
            [
                "WAITING_CUSTOMER",
                "RFID_ENROLLMENT_PENDING",
                "ACTIVE",
                "CHECKOUT_PENDING",
                "INSUFFICIENT_FUNDS",
                "CHECKOUT_PENDING",
            ],
        )
        self.assertEqual(
            matrix.events,
            [
                ("STARTUP", "WAITING_CUSTOMER"),
                ("RFID_SCANNING", "WAITING_CUSTOMER"),
                ("CLIENT_IDENTIFIED", "ACTIVE"),
                ("BASKET_INITIALIZED", "ACTIVE"),
                ("PRODUCT_ADDED", "ACTIVE"),
                ("PAYMENT_REQUESTED", "ACTIVE"),
                ("CHECKOUT_PENDING", "CHECKOUT_PENDING"),
                ("PAYMENT_SUCCESS", "CHECKOUT_PENDING"),
            ],
        )

    def test_product_detection_recovers_the_persistent_active_state_after_error(self) -> None:
        controller = HardwareController(HardwareConfig(enabled=False))
        matrix = _FakeMatrix()
        controller.matrix = matrix

        controller.show_error()
        controller.show_detection("ESP32", 0.95)

        self.assertEqual(matrix.states, ["ERROR", "ACTIVE"])
        self.assertEqual(matrix.events, [("PRODUCT_ADDED", "ACTIVE")])
        self.assertEqual(controller.matrix_state, "ACTIVE")


if __name__ == "__main__":
    unittest.main()
