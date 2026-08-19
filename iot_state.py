from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    WAITING_CUSTOMER = "WAITING_CUSTOMER"
    RFID_ENROLLMENT_PENDING = "RFID_ENROLLMENT_PENDING"
    ACTIVE = "ACTIVE"
    CHECKOUT_PENDING = "CHECKOUT_PENDING"
    PAYMENT_SUCCESS = "PAYMENT_SUCCESS"


@dataclass
class LocalDeviceState:
    device_id: str
    customer: dict[str, Any] | None = None
    session_status: SessionStatus = SessionStatus.WAITING_CUSTOMER
    backend_available: bool = True
    last_error: str | None = None
    last_label: str | None = None
    last_confidence: float | None = None
    reset_command_id: str | None = None
    mock_items: list[dict[str, Any]] = field(default_factory=list)

    def start_session(self, *, customer: dict[str, Any] | None) -> None:
        self.customer = customer or {}
        self.session_status = SessionStatus.ACTIVE
        self.last_error = None
        self.last_label = None
        self.last_confidence = None
        self.mock_items = []

    def mark_rfid_enrollment_pending(self) -> None:
        self.customer = None
        self.session_status = SessionStatus.RFID_ENROLLMENT_PENDING
        self.last_error = None
        self.last_label = None
        self.last_confidence = None
        self.mock_items = []

    def mark_detection(self, *, label: str, confidence: float) -> None:
        self.last_label = label
        self.last_confidence = confidence
        self.last_error = None

    def update_mock_items(self, items: Any) -> None:
        if items is None:
            return
        if isinstance(items, dict):
            self.mock_items = [
                {"label": str(label), "quantity": int(quantity)}
                for label, quantity in items.items()
                if int(quantity) > 0
            ]
            return
        if isinstance(items, list):
            normalized: list[dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                label = item.get("label")
                quantity = item.get("quantity")
                if label is None or quantity is None:
                    continue
                quantity = int(quantity)
                if quantity <= 0:
                    continue
                normalized.append({"label": str(label), "quantity": quantity})
            self.mock_items = normalized

    def mark_checkout_pending(self) -> None:
        self.session_status = SessionStatus.CHECKOUT_PENDING
        self.last_error = None

    def mark_payment_success(self, *, reset_command_id: str | None = None) -> None:
        self.session_status = SessionStatus.PAYMENT_SUCCESS
        self.reset_command_id = reset_command_id
        self.last_error = None

    def mark_api_result(self, *, ok: bool, error: str | None = None) -> None:
        self.backend_available = ok
        if ok:
            self.last_error = None
        elif error:
            self.last_error = error

    def reset_session(self) -> None:
        self.customer = None
        self.session_status = SessionStatus.WAITING_CUSTOMER
        self.last_error = None
        self.last_label = None
        self.last_confidence = None
        self.reset_command_id = None
        self.mock_items = []

    def preview_payload(self) -> dict[str, Any]:
        customer_name = None
        if isinstance(self.customer, dict):
            customer_name = (
                self.customer.get("display_name")
                or self.customer.get("name")
                or self.customer.get("full_name")
            )

        return {
            "device_id": self.device_id,
            "customer": customer_name,
            "session_status": self.session_status.value,
            "backend_available": self.backend_available,
            "last_error": self.last_error,
            "last_label": self.last_label,
            "last_confidence": self.last_confidence,
            "mock_items": [dict(item) for item in self.mock_items],
        }
