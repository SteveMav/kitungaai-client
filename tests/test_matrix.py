from __future__ import annotations

import unittest
import time

from matrix import Max7219Display, MatrixDisplay, render_frames_ascii, state_to_frames, text_to_frames
from matrix_animations import animation_names, get_animation
from hardware import HardwareConfig, HardwareController


class _FakeSpi:
    def __init__(self) -> None:
        self.opened: tuple[int, int] | None = None
        self.mode = None
        self.max_speed_hz = None
        self.transfers: list[list[int]] = []
        self.closed = False

    def open(self, bus: int, chip: int) -> None:
        self.opened = (bus, chip)

    def xfer2(self, payload: list[int]) -> None:
        self.transfers.append(payload)

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
            "PRODUCT_ADDED",
            "PAYMENT_REQUESTED",
            "CHECKOUT_PENDING",
            "PAYMENT_SUCCESS",
            "INSUFFICIENT_FUNDS",
            "ERROR",
        }
        self.assertTrue(required_states.issubset(set(animation_names())))

        for state in required_states:
            with self.subTest(state=state):
                animation = get_animation(state)
                self.assertTrue(animation.steps)
                for step in animation.steps:
                    self.assertEqual(len(step.frame), 8)
                    self.assertTrue(all(0 <= row <= 0xFF for row in step.frame))
                    self.assertGreater(step.duration, 0)

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

    def test_hardware_controller_maps_each_basket_stage_to_a_visual(self) -> None:
        controller = HardwareController(HardwareConfig(enabled=False))
        matrix = _FakeMatrix()
        controller.matrix = matrix

        controller.show_startup()
        controller.show_rfid_scanning()
        controller.show_rfid_enrollment_pending()
        controller.show_basket_initialized()
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
                "PAYMENT_SUCCESS",
            ],
        )
        self.assertEqual(
            matrix.events,
            [
                ("STARTUP", "WAITING_CUSTOMER"),
                ("RFID_SCANNING", "WAITING_CUSTOMER"),
                ("BASKET_INITIALIZED", "ACTIVE"),
                ("PRODUCT_ADDED", "ACTIVE"),
                ("PAYMENT_REQUESTED", "ACTIVE"),
                ("INSUFFICIENT_FUNDS", "CHECKOUT_PENDING"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
