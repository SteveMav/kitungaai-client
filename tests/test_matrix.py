from __future__ import annotations

import unittest

from matrix import Max7219Display, MatrixDisplay, render_frames_ascii, state_to_frames, text_to_frames


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
            cascaded=4,
            spi_factory=lambda: fake,
        )
        try:
            display.show_state("CHECKOUT_PENDING")
            self.assertTrue(fake.transfers)
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


if __name__ == "__main__":
    unittest.main()
