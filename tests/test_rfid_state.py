from __future__ import annotations

import unittest

from iot_state import LocalDeviceState, SessionStatus
from rfid import RC522RFIDReader, SimulationRFIDReader, _normalize_uid, build_rfid_reader


class FakeRC522Driver:
    def __init__(self, readings: list[object | None]) -> None:
        self.readings = readings

    def dev_read(self, address: int) -> int:
        return 0x92

    def read_id(self, *, as_number: bool = False) -> object | None:
        if not self.readings:
            return None
        return self.readings.pop(0)


class RFIDStateTest(unittest.TestCase):
    def test_simulation_reader_returns_uid_then_respects_interval(self) -> None:
        reader = SimulationRFIDReader(uid="04 a7 32 b1 9c", interval_seconds=30)
        self.assertEqual(reader.read_uid(), "04A732B19C")
        self.assertIsNone(reader.read_uid())

    def test_normalize_uid_accepts_hex_text_and_bytes(self) -> None:
        self.assertEqual(_normalize_uid("04 a7 32 b1 9c"), "04A732B19C")
        self.assertEqual(_normalize_uid("0x04:0xa7:0x32:0xb1:0x9c"), "04A732B19C")
        self.assertEqual(_normalize_uid([4, 167, 50, 177, 156]), "04A732B19C")
        self.assertEqual(_normalize_uid(bytes([4, 167, 50, 177, 156])), "04A732B19C")

    def test_build_rfid_reader_selects_hardware_reader(self) -> None:
        driver = FakeRC522Driver([[0x04, 0xA7, 0x32, 0xB1, 0x9C]])
        reader = build_rfid_reader(
            mode="hardware",
            hardware_driver=driver,
            check_hardware_device_path=False,
        )
        self.assertIsInstance(reader, RC522RFIDReader)
        self.assertEqual(reader.read_uid(), "04A732B19C")

    def test_hardware_reader_returns_once_until_card_is_removed_and_rearmed(self) -> None:
        driver = FakeRC522Driver(
            [
                [0x04, 0xA7, 0x32, 0xB1, 0x9C],
                [0x04, 0xA7, 0x32, 0xB1, 0x9C],
                None,
                [0x04, 0xA7, 0x32, 0xB1, 0x9C],
                None,
                None,
                [0x04, 0xA7, 0x32, 0xB1, 0x9C],
            ]
        )
        reader = RC522RFIDReader(
            driver=driver,
            check_device_path=False,
            absent_reads_to_rearm=2,
        )

        self.assertEqual(reader.read_uid(), "04A732B19C")
        self.assertIsNone(reader.read_uid())
        self.assertIsNone(reader.read_uid())
        self.assertIsNone(reader.read_uid())
        self.assertIsNone(reader.read_uid())
        self.assertIsNone(reader.read_uid())
        self.assertEqual(reader.read_uid(), "04A732B19C")

    def test_local_state_transitions(self) -> None:
        state = LocalDeviceState(device_id="KITUNGA-PI-001")
        self.assertEqual(state.session_status, SessionStatus.WAITING_CUSTOMER)

        state.mark_rfid_enrollment_pending()
        self.assertEqual(state.session_status, SessionStatus.RFID_ENROLLMENT_PENDING)

        state.start_session(customer={"display_name": "Monsieur X"})
        self.assertEqual(state.session_status, SessionStatus.ACTIVE)
        self.assertEqual(state.preview_payload()["customer"], "Monsieur X")

        state.mark_checkout_pending()
        self.assertEqual(state.session_status, SessionStatus.CHECKOUT_PENDING)

        state.mark_payment_success(reset_command_id="test-command")
        self.assertEqual(state.session_status, SessionStatus.PAYMENT_SUCCESS)
        self.assertEqual(state.reset_command_id, "test-command")

        state.reset_session()
        self.assertEqual(state.session_status, SessionStatus.WAITING_CUSTOMER)
        self.assertIsNone(state.reset_command_id)


if __name__ == "__main__":
    unittest.main()
