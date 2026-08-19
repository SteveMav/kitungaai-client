from __future__ import annotations

import unittest
from unittest.mock import patch

from hardware import HardwareConfig, HardwareController


class _FakeBuzzer:
    def __init__(
        self,
        pin: int,
        *,
        active_high: bool,
        initial_value: bool,
        frequency: int | None = None,
    ) -> None:
        self.pin = pin
        self.active_high = active_high
        self._frequency = frequency
        self.frequency_values: list[int] = []
        if frequency is not None:
            self.frequency_values.append(frequency)
        self.logical_values: list[float] = []
        self.physical_values: list[float] = []
        self.closed = False
        self.fail_on_on = False
        self.fail_on_value = False
        self._write(initial_value)

    @property
    def value(self) -> float:
        return self.logical_values[-1]

    @value.setter
    def value(self, logical_value: float) -> None:
        if self.fail_on_value:
            raise RuntimeError("simulated pwm failure")
        self._write(logical_value)

    @property
    def frequency(self) -> int | None:
        return self._frequency

    @frequency.setter
    def frequency(self, frequency: int | None) -> None:
        self._frequency = frequency
        if frequency is not None:
            self.frequency_values.append(frequency)

    def _write(self, logical_value: float) -> None:
        logical_value = float(logical_value)
        self.logical_values.append(logical_value)
        self.physical_values.append(logical_value if self.active_high else 1.0 - logical_value)

    def on(self) -> None:
        if self.fail_on_on:
            raise RuntimeError("simulated buzzer failure")
        self._write(1.0)

    def off(self) -> None:
        self._write(0.0)

    def close(self) -> None:
        self.closed = True


class BuzzerTest(unittest.TestCase):
    def _controller(
        self,
        *,
        active_high: bool,
        buzzer_type: str = "passive",
        frequency_hz: int = 2000,
    ) -> tuple[HardwareController, _FakeBuzzer]:
        fake: _FakeBuzzer | None = None

        def factory(*args: object, **kwargs: object) -> _FakeBuzzer:
            nonlocal fake
            fake = _FakeBuzzer(*args, **kwargs)
            return fake

        controller = HardwareController(
            HardwareConfig(
                enabled=True,
                pir_pin=None,
                buzzer_pin=18,
                buzzer_active_high=active_high,
                buzzer_type=buzzer_type,
                buzzer_frequency_hz=frequency_hz,
                buzzer_factory=factory,
                matrix_enabled=False,
            )
        )
        assert fake is not None
        return controller, fake

    def test_buzzer_initializes_off_for_both_polarities(self) -> None:
        for active_high, expected_physical_off in ((True, False), (False, True)):
            with self.subTest(active_high=active_high):
                controller, fake = self._controller(active_high=active_high)
                try:
                    self.assertEqual(fake.pin, 18)
                    self.assertEqual(fake.logical_values[-1], 0.0)
                    self.assertEqual(fake.physical_values[-1], expected_physical_off)
                finally:
                    controller.close()

    def test_buzzer_config_defaults_keep_gpio18_active_low(self) -> None:
        config = HardwareConfig(
            pir_pin=None,
            buzzer_factory=lambda *args, **kwargs: _FakeBuzzer(*args, **kwargs),
            matrix_enabled=False,
        )
        self.assertEqual(config.buzzer_pin, 18)
        self.assertIs(config.buzzer_active_high, False)
        self.assertEqual(config.buzzer_type, "passive")
        self.assertEqual(config.buzzer_frequency_hz, 2000)

    def test_passive_buzzer_patterns_use_pwm_tone_and_return_off(self) -> None:
        controller, fake = self._controller(active_high=False)
        try:
            before_waiting = len(fake.logical_values)
            controller.show_waiting()
            self.assertEqual(len(fake.logical_values), before_waiting)

            with patch("hardware.time.sleep", return_value=None):
                controller.beep_detection()
                self.assertEqual(fake.logical_values[-1], 0.0)
                self.assertIn(0.5, fake.logical_values)
                self.assertIn(2000, fake.frequency_values)

                controller.beep_payment_success()
                self.assertEqual(fake.logical_values[-1], 0.0)

                controller.beep_error()
                self.assertEqual(fake.logical_values[-1], 0.0)
                self.assertIn(1000, fake.frequency_values)
        finally:
            controller.close()

    def test_active_buzzer_mode_still_uses_on_off_and_returns_off(self) -> None:
        controller, fake = self._controller(active_high=True, buzzer_type="active")
        try:
            with patch("hardware.time.sleep", return_value=None):
                controller.beep_detection()
            self.assertEqual(fake.logical_values[-1], 0.0)
            self.assertIn(1.0, fake.logical_values)
            self.assertNotIn(0.5, fake.logical_values)
        finally:
            controller.close()

    def test_buzzer_returns_off_when_passive_activation_fails(self) -> None:
        controller, fake = self._controller(active_high=False)
        try:
            fake.fail_on_value = True
            with patch("hardware.time.sleep", return_value=None):
                controller.beep_detection()
            self.assertEqual(fake.logical_values[-1], 0.0)
        finally:
            controller.close()


if __name__ == "__main__":
    unittest.main()
