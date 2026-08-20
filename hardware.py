from __future__ import annotations
# matrix.MatrixDisplay is imported when setting up the matrix to avoid
# import-time errors on systems without the matrix module.
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable

from config import (
    BUZZER_ACTIVE_HIGH,
    BUZZER_FREQUENCY_HZ,
    BUZZER_PIN,
    BUZZER_TYPE,
)


@dataclass(frozen=True)
class HardwareConfig:
    enabled: bool = True
    # PIR
    pir_pin: int | None = 27
    pir_active_high: bool = True
    # Buzzer
    buzzer_pin: int | None = BUZZER_PIN
    buzzer_active_high: bool = BUZZER_ACTIVE_HIGH
    buzzer_type: str = BUZZER_TYPE
    buzzer_frequency_hz: int = BUZZER_FREQUENCY_HZ
    buzzer_factory: Callable[..., Any] | None = None
    # Matrix
    matrix_enabled: bool = True
    matrix_device: str = "/dev/spidev0.0"
    matrix_intensity: int = 2
    matrix_speed_hz: int = 1_000_000
    matrix_cascaded: int = 1
    matrix_reverse_order: bool = False


class HardwareController:
    def __init__(self, config: HardwareConfig) -> None:
        self.config = config
        # GPIO
        self.pir_sensor: Any | None = None
        self.buzzer: Any | None = None
        # Matrix
        self.matrix: Any | None = None
        # Etats
        self.gpio_ready = False
        self.pir_ready = False
        self.buzzer_ready = False
        self.matrix_ready = False
        self.last_presence: bool | None = None
        self.matrix_state: str | None = None

        if not config.enabled:
            logging.info("GPIO hardware disabled by configuration.")
            return

        self._setup_gpio()
        self._setup_matrix()

    def _setup_gpio(self) -> None:
        DigitalInputDevice = None
        DigitalOutputDevice = None
        PWMOutputDevice = None
        needs_gpiozero = self.config.pir_pin is not None or (
            self.config.buzzer_pin is not None and self.config.buzzer_factory is None
        )
        if needs_gpiozero:
            try:
                from gpiozero import DigitalInputDevice, DigitalOutputDevice, PWMOutputDevice
            except ImportError:
                logging.warning("gpiozero is not installed; PIR and buzzer are disabled.")
        # PIR

        if self.config.pir_pin is not None and DigitalInputDevice is not None:
            try:
                self.pir_sensor = DigitalInputDevice(
                    self.config.pir_pin,
                    pull_up=False,
                    bounce_time=0.05,
                )

                self.pir_ready = True

                logging.info(
                    "PIR sensor ready on GPIO %s",
                    self.config.pir_pin,
                )

            except Exception as exc:
                logging.warning(
                    "Could not initialize PIR sensor on GPIO %s: %s",
                    self.config.pir_pin,
                    exc,
                )

#BUZZER
        if self.config.buzzer_pin is not None:
            try:
                buzzer_type = self._normalized_buzzer_type()
                if buzzer_type == "passive":
                    buzzer_factory = self.config.buzzer_factory or PWMOutputDevice
                else:
                    buzzer_factory = self.config.buzzer_factory or DigitalOutputDevice
                if buzzer_factory is None:
                    raise RuntimeError("gpiozero buzzer output device is unavailable")

                buzzer_kwargs: dict[str, Any] = {
                    "active_high": self.config.buzzer_active_high,
                    "initial_value": False,
                }
                if buzzer_type == "passive":
                    buzzer_kwargs["frequency"] = self._buzzer_frequency()

                self.buzzer = buzzer_factory(self.config.buzzer_pin, **buzzer_kwargs)

                self._buzzer_off()
                self.buzzer_ready = True

                logging.info(
                    "Buzzer ready on GPIO %s type=%s active_high=%s frequency_hz=%s",
                    self.config.buzzer_pin,
                    buzzer_type,
                    self.config.buzzer_active_high,
                    self._buzzer_frequency(),
                )

            except Exception as exc:
                logging.warning(
                    "Could not initialize buzzer on GPIO %s: %s",
                    self.config.buzzer_pin,
                    exc,
                )

        self.gpio_ready = any(
            (
                self.pir_ready,
                self.buzzer_ready,
            )
        )
    def _setup_matrix(self) -> None:
        if not self.config.matrix_enabled:
            logging.info("Matrix disabled by configuration.")
            return

        try:
            # Try relative import first (when package-installed), then absolute.
            try:
                from .matrix import MatrixDisplay  # type: ignore
            except Exception:
                from matrix import MatrixDisplay

            self.matrix = MatrixDisplay(
                device=self.config.matrix_device,
                intensity=self.config.matrix_intensity,
                speed_hz=self.config.matrix_speed_hz,
                cascaded=self.config.matrix_cascaded,
                reverse_order=self.config.matrix_reverse_order,
            )
            self.matrix_ready = True

            logging.info("Matrix display ready.")

        except ImportError:
            logging.warning(
                "matrix.py is not available yet; Matrix disabled."
            )

        except Exception as exc:
            logging.warning(
                "Could not initialize Matrix: %s",
                exc,
            )


    def presence_detected(self) -> bool:
        """
        Retourne True lorsqu'une présence est détectée par le PIR.
        """

        if self.pir_sensor is None:
            # Si le PIR est indisponible, ne pas bloquer la vision.
            return True

        try:
            raw_value = bool(self.pir_sensor.value)

        except Exception as exc:
            logging.warning(
                "Could not read PIR sensor: %s",
                exc,
            )

            # En cas de problème PIR, on laisse la vision fonctionner.
            return True

        if self.config.pir_active_high:
            return raw_value

        return not raw_value

    def apply_presence(self, presence: bool) -> None:
        """
        Journalise uniquement les changements d'état du PIR.
        """

        if presence == self.last_presence:
            return

        self.last_presence = presence

        if presence:
            logging.info("PIR presence: detected")
        else:
            logging.info("PIR presence: waiting")
# BUZZER
    def _normalized_buzzer_type(self) -> str:
        buzzer_type = str(self.config.buzzer_type).strip().lower()
        if buzzer_type not in {"active", "passive"}:
            raise ValueError("BUZZER_TYPE must be 'active' or 'passive'")
        return buzzer_type

    def _buzzer_frequency(self, frequency_hz: int | None = None) -> int:
        frequency = self.config.buzzer_frequency_hz if frequency_hz is None else frequency_hz
        return max(1, int(frequency))

    def _buzzer_on(self, *, frequency_hz: int | None = None) -> None:
        if self.buzzer is None:
            return

        if self._normalized_buzzer_type() == "passive":
            frequency = self._buzzer_frequency(frequency_hz)
            if hasattr(self.buzzer, "frequency"):
                self.buzzer.frequency = frequency
            self.buzzer.value = 0.5
            return

        self.buzzer.on()

    def _buzzer_off(self) -> None:
        if self.buzzer is None:
            return
        try:
            self.buzzer.off()
        except Exception as exc:
            logging.warning(
                "Could not switch buzzer off: %s",
                exc,
            )

    def beep(self, duration: float = 0.10, *, frequency_hz: int | None = None) -> None:
        if self.buzzer is None:
            return

        try:
            self._buzzer_on(frequency_hz=frequency_hz)
            time.sleep(duration)

        except Exception as exc:
            logging.warning(
                "Could not activate buzzer: %s",
                exc,
            )
        finally:
            self._buzzer_off()

    def beep_detection(self) -> None:
        """
        Produit correctement détecté / accepté.
        """

        self.beep(0.12)

    def beep_payment_success(self) -> None:
        """
        Paiement reussi: deux bips courts.
        """

        try:
            self.beep(0.10)
            time.sleep(0.08)
            self.beep(0.10)
        finally:
            self._buzzer_off()

    def beep_error(self) -> None:
        """
        Erreur de traitement ou communication.
        """

        try:
            error_frequency = max(120, self._buzzer_frequency() // 2)
            self.beep(0.18, frequency_hz=error_frequency)
            time.sleep(0.08)
            self.beep(0.18, frequency_hz=error_frequency)
        finally:
            self._buzzer_off()

    def beep_ready(self) -> None:
        """
        Le code panier est prêt à être scanné.
        """

        try:
            self.beep(0.10)
            time.sleep(0.10)
            self.beep(0.10)
        finally:
            self._buzzer_off()

    # MATRIX

    def show_startup(self) -> None:
        self.show_matrix_state("WAITING_CUSTOMER")
        self.show_matrix_event("STARTUP")

    def show_waiting(self) -> None:
        self.show_matrix_state("WAITING_CUSTOMER")

    def show_rfid_scanning(self) -> None:
        self.show_matrix_event("RFID_SCANNING")

    def show_rfid_enrollment_pending(self) -> None:
        self.show_matrix_state("RFID_ENROLLMENT_PENDING")

    def show_client_identified(self) -> None:
        self.show_basket_initialized()

    def show_basket_initialized(self) -> None:
        self.show_matrix_state("ACTIVE")
        self.show_matrix_event("BASKET_INITIALIZED")

    def show_payment_requested(self) -> None:
        self.show_matrix_event("PAYMENT_REQUESTED")

    def show_checkout_pending(self) -> None:
        self.show_matrix_state("CHECKOUT_PENDING")

    def show_payment_success(self) -> None:
        self.show_matrix_state("PAYMENT_SUCCESS")

    def show_insufficient_funds(self) -> None:
        self.show_matrix_state("CHECKOUT_PENDING")
        self.show_matrix_event("INSUFFICIENT_FUNDS")

    def show_error(self) -> None:
        self.show_matrix_event("ERROR")

    def show_matrix_state(self, state: str) -> None:
        normalized = state.strip().upper()
        if normalized == self.matrix_state:
            return
        self.matrix_state = normalized
        if self.matrix is None:
            return

        try:
            self.matrix.show_state(normalized)
        except Exception as exc:
            logging.warning(
                "Could not display state on Matrix: %s",
                exc,
            )

    def show_matrix_event(self, state: str) -> None:
        if self.matrix is None:
            return

        try:
            self.matrix.play_animation(state, resume_state=self.matrix_state)
        except Exception as exc:
            logging.warning(
                "Could not display event on Matrix: %s",
                exc,
            )

    def show_detection(
        self,
        label: str,
        confidence: float,
    ) -> None:
        """
        Affiche une détection produit sur la Matrix.
        """

        if self.matrix is None:
            return

        try:
            self.matrix.show_detection(
                label,
                confidence,
            )

        except Exception as exc:
            logging.warning(
                "Could not display detection on Matrix: %s",
                exc,
            )

    def clear_matrix(self) -> None:
        if self.matrix is None:
            return

        with suppress(Exception):
            self.matrix.clear()

    # ============================================================
    # STATUS


    def status_payload(
        self,
        *,
        presence: bool,
    ) -> dict:
        return {
            "enabled": self.config.enabled,
            "gpio_ready": self.gpio_ready,

            "pir_ready": self.pir_ready,
            "buzzer_ready": self.buzzer_ready,
            "matrix_ready": self.matrix_ready,

            "presence_detected": presence,

            "pir_pin": self.config.pir_pin,
            "buzzer_pin": self.config.buzzer_pin,
            "buzzer_active_high": self.config.buzzer_active_high,
            "buzzer_type": self.config.buzzer_type,
            "buzzer_frequency_hz": self.config.buzzer_frequency_hz,
            "matrix_state": self.matrix_state,
            "matrix_device": self.config.matrix_device,
        }

    # CLEANUP
    def close(self) -> None:
        if self.buzzer is not None:
            self._buzzer_off()

        for device in (
            self.pir_sensor,
            self.buzzer,
        ):
            if device is not None:
                with suppress(Exception):
                    device.close()

        if self.matrix is not None:
            with suppress(Exception):
                self.matrix.close()
