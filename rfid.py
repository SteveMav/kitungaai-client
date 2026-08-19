from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
import time
from typing import Any, Protocol

from config import (
    RFID_ABSENT_READS_TO_REARM,
    RFID_MODE,
    RFID_RST_PIN,
    RFID_SPI_BUS,
    RFID_SPI_DEVICE,
    RFID_SPI_SPEED_HZ,
    SIMULATED_RFID_INTERVAL_SECONDS,
    SIMULATED_RFID_UID,
)

logger = logging.getLogger(__name__)
VERSION_REG = 0x37


class RFIDReader(Protocol):
    def read_uid(self) -> str | None:
        ...


class RFIDHardwareError(RuntimeError):
    """Erreur lisible lors de l'initialisation ou lecture RFID hardware."""


class SimulationRFIDReader:
    def __init__(
        self,
        *,
        uid: str = SIMULATED_RFID_UID,
        interval_seconds: float = SIMULATED_RFID_INTERVAL_SECONDS,
    ) -> None:
        self.uid = _normalize_uid(uid)
        self.interval_seconds = max(0.0, interval_seconds)
        self._next_read_at = 0.0

    def read_uid(self) -> str | None:
        now = time.monotonic()
        if now < self._next_read_at:
            return None

        self._next_read_at = now + self.interval_seconds
        return self.uid


class RC522RFIDReader:
    """Lecteur MFRC522/RC522 sur SPI, expose uniquement read_uid()."""

    def __init__(
        self,
        *,
        spi_bus: int = RFID_SPI_BUS,
        spi_device: int = RFID_SPI_DEVICE,
        rst_pin: int = RFID_RST_PIN,
        spi_speed_hz: int = RFID_SPI_SPEED_HZ,
        absent_reads_to_rearm: int = RFID_ABSENT_READS_TO_REARM,
        driver: Any | None = None,
        driver_factory: Callable[..., Any] | None = None,
        check_device_path: bool = True,
    ) -> None:
        self.spi_bus = int(spi_bus)
        self.spi_device = int(spi_device)
        self.rst_pin = int(rst_pin)
        self.spi_speed_hz = int(spi_speed_hz)
        self.absent_reads_to_rearm = max(1, int(absent_reads_to_rearm))
        self.device_path = f"/dev/spidev{self.spi_bus}.{self.spi_device}"
        self._present_uid: str | None = None
        self._absent_reads = self.absent_reads_to_rearm
        self._closed = False

        if check_device_path:
            self._ensure_spi_device_exists()

        self._driver = driver if driver is not None else self._build_driver(driver_factory)
        self.version = self._read_version()
        if self.version in (0x00, 0xFF):
            raise RFIDHardwareError(
                "RC522 not detected on "
                f"{self.device_path} (VersionReg=0x{self.version:02X}). "
                "Check 3.3V, GND, SCK GPIO11, MOSI GPIO10, MISO GPIO9, "
                f"SDA/SS CE1 GPIO7 and RST GPIO{self.rst_pin}."
            )

    def read_uid(self) -> str | None:
        if self._closed:
            return None

        try:
            raw_uid = self._driver.read_id(as_number=False)
        except Exception as exc:
            logger.warning("RFID hardware read failed: %s", exc)
            return None

        if raw_uid is None:
            self._mark_absent_read()
            return None

        try:
            uid = _normalize_uid(raw_uid)
        except ValueError as exc:
            logger.warning("RFID hardware returned an invalid UID %r: %s", raw_uid, exc)
            return None

        self._absent_reads = 0
        if uid == self._present_uid:
            return None

        self._present_uid = uid
        return uid

    def close(self) -> None:
        self._closed = True
        spi = getattr(self._driver, "spi", None)
        close = getattr(spi, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                logger.debug("Could not close RFID SPI device: %s", exc)

    def _ensure_spi_device_exists(self) -> None:
        if Path(self.device_path).exists():
            return
        raise RFIDHardwareError(
            f"{self.device_path} not found. SPI may be disabled or CE1 is unavailable. "
            "Enable SPI with raspi-config and verify that /dev/spidev0.1 exists."
        )

    def _build_driver(self, driver_factory: Callable[..., Any] | None) -> Any:
        if driver_factory is not None:
            try:
                return driver_factory(
                    bus=self.spi_bus,
                    device=self.spi_device,
                    speed=self.spi_speed_hz,
                    pin_rst=self.rst_pin,
                    pin_irq=None,
                )
            except Exception as exc:
                raise RFIDHardwareError(f"Could not initialize RC522 driver: {exc}") from exc

        try:
            import RPi.GPIO as GPIO  # type: ignore[import-not-found]
            from pirc522 import RFID  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RFIDHardwareError(
                "Missing RC522 dependency. Install the client requirements so "
                "`pi-rc522`, `spidev` and an RPi.GPIO-compatible provider are available."
            ) from exc

        try:
            return RFID(
                bus=self.spi_bus,
                device=self.spi_device,
                speed=self.spi_speed_hz,
                pin_rst=self.rst_pin,
                pin_irq=None,
                pin_mode=GPIO.BCM,
            )
        except FileNotFoundError as exc:
            raise RFIDHardwareError(
                f"Could not open {self.device_path}. SPI may be disabled."
            ) from exc
        except PermissionError as exc:
            raise RFIDHardwareError(
                f"Permission denied opening {self.device_path}. Run as a user allowed to access SPI/GPIO."
            ) from exc
        except Exception as exc:
            raise RFIDHardwareError(
                f"Could not initialize RC522 on {self.device_path} with RST GPIO{self.rst_pin}: {exc}"
            ) from exc

    def _read_version(self) -> int:
        dev_read = getattr(self._driver, "dev_read", None)
        if not callable(dev_read):
            return 0x92
        try:
            return int(dev_read(VERSION_REG)) & 0xFF
        except Exception as exc:
            raise RFIDHardwareError(f"Could not communicate with RC522 on {self.device_path}: {exc}") from exc

    def _mark_absent_read(self) -> None:
        if self._absent_reads < self.absent_reads_to_rearm:
            self._absent_reads += 1
        if self._absent_reads >= self.absent_reads_to_rearm:
            self._present_uid = None


HardwareRFIDReader = RC522RFIDReader


def build_rfid_reader(
    *,
    mode: str = RFID_MODE,
    simulated_uid: str = SIMULATED_RFID_UID,
    simulated_interval_seconds: float = SIMULATED_RFID_INTERVAL_SECONDS,
    spi_bus: int = RFID_SPI_BUS,
    spi_device: int = RFID_SPI_DEVICE,
    rst_pin: int = RFID_RST_PIN,
    spi_speed_hz: int = RFID_SPI_SPEED_HZ,
    absent_reads_to_rearm: int = RFID_ABSENT_READS_TO_REARM,
    hardware_driver: Any | None = None,
    hardware_driver_factory: Callable[..., Any] | None = None,
    check_hardware_device_path: bool = True,
) -> RFIDReader:
    normalized_mode = mode.strip().lower()
    if normalized_mode == "simulation":
        return SimulationRFIDReader(
            uid=simulated_uid,
            interval_seconds=simulated_interval_seconds,
        )
    if normalized_mode == "hardware":
        return RC522RFIDReader(
            spi_bus=spi_bus,
            spi_device=spi_device,
            rst_pin=rst_pin,
            spi_speed_hz=spi_speed_hz,
            absent_reads_to_rearm=absent_reads_to_rearm,
            driver=hardware_driver,
            driver_factory=hardware_driver_factory,
            check_device_path=check_hardware_device_path,
        )
    raise ValueError("RFID_MODE must be 'simulation' or 'hardware'")


def _normalize_uid(uid: object) -> str:
    if isinstance(uid, (bytes, bytearray)):
        return _normalize_uid_bytes(uid)

    if isinstance(uid, Sequence) and not isinstance(uid, str):
        return _normalize_uid_bytes(uid)

    text = str(uid).strip().upper().replace("0X", "")
    for separator in (" ", "\t", "\r", "\n", ":", "-", "_"):
        text = text.replace(separator, "")

    if not text:
        raise ValueError("empty UID")
    if len(text) % 2 != 0:
        raise ValueError("hex UID must have an even number of characters")
    if any(character not in "0123456789ABCDEF" for character in text):
        raise ValueError("UID must contain only hexadecimal characters")
    return text


def _normalize_uid_bytes(uid: Sequence[int]) -> str:
    normalized: list[str] = []
    for value in uid:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("UID byte sequence must contain integers")
        if not 0 <= value <= 0xFF:
            raise ValueError("UID byte values must be between 0 and 255")
        normalized.append(f"{value:02X}")

    if not normalized:
        raise ValueError("empty UID")
    return "".join(normalized)
