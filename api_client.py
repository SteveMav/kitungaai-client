from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

from config import (
    API_BASE_URL,
    API_MODE,
    DEVICE_ID,
    MOCK_CUSTOMER_ID,
    MOCK_CUSTOMER_NAME,
    REQUEST_TIMEOUT,
    SIMULATED_RFID_UID,
)


@dataclass(frozen=True)
class ApiResult:
    ok: bool
    status: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    status_code: int | None = None


class KitungaApiClient(Protocol):
    def start_session(self, rfid_uid: str) -> ApiResult:
        ...

    def send_detection(
        self,
        label: str,
        confidence: float,
        *,
        detection_id: str | None = None,
        action: str = "ITEM_ADDED",
    ) -> ApiResult:
        ...

    def get_invoice_status(self) -> ApiResult:
        ...

    def confirm_rfid_payment(self, rfid_uid: str) -> ApiResult:
        ...

    def acknowledge_reset(self, command_id: str) -> ApiResult:
        ...


class MockApiClient:
    """In-memory simulator for one active invoice on one Raspberry Pi."""

    def __init__(
        self,
        *,
        device_id: str = DEVICE_ID,
        known_rfid_uid: str = SIMULATED_RFID_UID,
        customer_name: str = MOCK_CUSTOMER_NAME,
        customer_id: str = MOCK_CUSTOMER_ID,
    ) -> None:
        self.device_id = device_id
        self.known_rfid_uid = _normalize_uid(known_rfid_uid)
        self.customer = {
            "id": customer_id,
            "name": customer_name,
            "display_name": customer_name,
        }
        self._session: dict[str, Any] | None = None

    def start_session(self, rfid_uid: str) -> ApiResult:
        normalized_uid = _normalize_uid(rfid_uid)
        if normalized_uid != self.known_rfid_uid:
            return ApiResult(
                ok=False,
                status="UNKNOWN_RFID",
                error="RFID card is not recognized by mock.",
            )

        if self._session is None or self._session["status"] == "PAID":
            self._session = {
                "customer": dict(self.customer),
                "status": "ACTIVE",
                "detections": [],
                "items": {},
                "rfid_uid": normalized_uid,
            }
        return ApiResult(
            ok=True,
            status=self._session["status"],
            data={
                "device_id": self.device_id,
                "customer": dict(self.customer),
                "mock_items": _mock_items_payload(self._session),
                "status": self._session["status"],
                "message": "Mock invoice active",
            },
        )

    def send_detection(
        self,
        label: str,
        confidence: float,
        *,
        detection_id: str | None = None,
        action: str = "ITEM_ADDED",
    ) -> ApiResult:
        session = self._session
        if session is None:
            return ApiResult(
                ok=False,
                status="NO_ACTIVE_INVOICE",
                error="Mock invoice is not active.",
            )
        if session["status"] != "ACTIVE":
            return ApiResult(
                ok=False,
                status=session["status"],
                error=f"Mock invoice is not active: {session['status']}",
            )

        normalized_action = str(action).strip().upper()
        if normalized_action not in {"ITEM_ADDED", "ITEM_REMOVED"}:
            return ApiResult(
                ok=False,
                status="INVALID_DETECTION_ACTION",
                error=f"Unsupported mock detection action: {action}",
                status_code=422,
            )

        items = session.setdefault("items", {})
        current_quantity = int(items.get(label, 0))
        if normalized_action == "ITEM_REMOVED" and current_quantity < 1:
            return ApiResult(
                ok=False,
                status="INVALID_REMOVAL",
                error=f"Mock basket does not contain {label}",
                status_code=422,
            )

        detection = {
            "label": label,
            "confidence": round(float(confidence), 4),
            "action": normalized_action,
            "accepted": True,
        }
        session["detections"].append(detection)
        if normalized_action == "ITEM_ADDED":
            items[label] = current_quantity + 1
        elif current_quantity == 1:
            items.pop(label, None)
        else:
            items[label] = current_quantity - 1
        return ApiResult(
            ok=True,
            status="PRODUCT_ADDED" if normalized_action == "ITEM_ADDED" else "PRODUCT_REMOVED",
            data={
                "label": label,
                "confidence": detection["confidence"],
                "action": normalized_action,
                "accepted": True,
                "mock_items": _mock_items_payload(session),
                "status": session["status"],
                "message": "Mock product accepted",
            },
        )

    def get_invoice_status(self) -> ApiResult:
        if self._session is None:
            return ApiResult(ok=True, status="IDLE", data={"status": "IDLE"})
        return ApiResult(
            ok=True,
            status=self._session["status"],
            data={
                "status": self._session["status"],
                "detections_count": len(self._session["detections"]),
                "mock_items": _mock_items_payload(self._session),
            },
        )

    def confirm_rfid_payment(self, rfid_uid: str) -> ApiResult:
        session = self._session
        if session is None:
            return ApiResult(
                ok=False,
                status="NO_ACTIVE_INVOICE",
                error="Mock invoice is not active.",
            )
        if _normalize_uid(rfid_uid) != session["rfid_uid"]:
            return ApiResult(
                ok=False,
                status="RFID_MISMATCH",
                error="Payment RFID does not match the active customer",
            )
        if session["status"] not in {"ACTIVE", "CHECKOUT_PENDING"}:
            return ApiResult(
                ok=False,
                status=session["status"],
                error="Mock invoice is no longer available for payment",
            )

        session["status"] = "PAID"
        return ApiResult(
            ok=True,
            status="PAID",
            data={
                "status": "PAID",
                "payment_status": "PAID",
                "mock_items": _mock_items_payload(session),
                "message": "Mock RFID payment accepted",
            },
        )

    def acknowledge_reset(self, command_id: str) -> ApiResult:
        return ApiResult(ok=True, status="ACKNOWLEDGED", data={"command_id": command_id})

    def get_mock_invoice(self) -> dict[str, int]:
        if self._session is None:
            return {}
        return dict(self._session.get("items", {}))

    def reset_session(self) -> None:
        self._session = None


def _mock_items_payload(session: dict[str, Any]) -> list[dict[str, Any]]:
    items = session.get("items") or {}
    return [
        {"label": label, "quantity": int(quantity)}
        for label, quantity in items.items()
        if int(quantity) > 0
    ]


class RealApiClient:
    """HTTP client whose only persistent identity is the configured device_id."""

    INVOICE_ROOT = "/api/iot/devices/{device_id}/invoice"
    ACK_RESET_PATH = "/api/v1/devices/{device_id}/commands/{command_id}/ack"

    def __init__(
        self,
        *,
        base_url: str = API_BASE_URL,
        device_id: str = DEVICE_ID,
        timeout: float = REQUEST_TIMEOUT,
        session: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.device_id = device_id
        self.timeout = timeout
        self.session = session or requests.Session()
        self._pending_detection_keys: dict[str, str] = {}
        self._pending_payment_keys: dict[str, str] = {}

    @property
    def invoice_root(self) -> str:
        return self.INVOICE_ROOT.format(device_id=self.device_id)

    def start_session(self, rfid_uid: str) -> ApiResult:
        return self._request(
            "POST",
            f"{self.invoice_root}/start/",
            json_data={"rfid_uid": _normalize_uid(rfid_uid)},
        )

    def send_detection(
        self,
        label: str,
        confidence: float,
        *,
        detection_id: str | None = None,
        action: str = "ITEM_ADDED",
    ) -> ApiResult:
        normalized_action = str(action).strip().upper()
        request_key = f"{normalized_action}:{detection_id}" if detection_id else str(uuid.uuid4())
        idempotency_key = self._pending_detection_keys.setdefault(request_key, str(uuid.uuid4()))
        result = self._request(
            "POST",
            f"{self.invoice_root}/detections/",
            json_data={
                "label": label,
                "confidence": round(float(confidence), 4),
                "action": normalized_action,
            },
            idempotency_key=idempotency_key,
        )
        if result.status_code is not None:
            self._pending_detection_keys.pop(request_key, None)
        return result

    def get_invoice_status(self) -> ApiResult:
        return self._request("GET", f"{self.invoice_root}/status/")

    def confirm_rfid_payment(self, rfid_uid: str) -> ApiResult:
        normalized_uid = _normalize_uid(rfid_uid)
        idempotency_key = self._pending_payment_keys.setdefault(normalized_uid, str(uuid.uuid4()))
        result = self._request(
            "POST",
            f"{self.invoice_root}/rfid-payment/",
            json_data={"rfid_uid": normalized_uid},
            idempotency_key=idempotency_key,
        )
        if result.status_code is not None:
            self._pending_payment_keys.pop(normalized_uid, None)
        return result

    def acknowledge_reset(self, command_id: str) -> ApiResult:
        return self._request(
            "POST",
            self.ACK_RESET_PATH.format(device_id=self.device_id, command_id=command_id),
            json_data={},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> ApiResult:
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self.session.request(
                method,
                url,
                json=json_data,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            return ApiResult(ok=False, status="TIMEOUT", error=str(exc))
        except requests.ConnectionError as exc:
            return ApiResult(ok=False, status="CONNECTION_ERROR", error=str(exc))
        except requests.RequestException as exc:
            return ApiResult(ok=False, status="REQUEST_ERROR", error=str(exc))

        try:
            data = response.json()
        except ValueError:
            data = {}
            json_error = "Backend returned invalid JSON"
        else:
            json_error = None

        if not 200 <= response.status_code < 300:
            payload_status = _status_from_payload(data)
            if response.status_code == 401:
                return ApiResult(
                    ok=False,
                    status="DEVICE_UNAUTHORIZED",
                    data=data if isinstance(data, dict) else {},
                    error="Device identifier was rejected (401). Verify DEVICE_ID and that the device is enabled in Django.",
                    status_code=response.status_code,
                )
            if response.status_code == 404 and not payload_status:
                return ApiResult(
                    ok=False,
                    status="API_ROUTE_NOT_FOUND",
                    data=data if isinstance(data, dict) else {},
                    error="Backend endpoint was not found (404). Restart the updated Django server and verify API_BASE_URL.",
                    status_code=response.status_code,
                )
            message = _error_from_payload(data) or response.reason or "HTTP error"
            return ApiResult(
                ok=False,
                status=payload_status or "HTTP_ERROR",
                data=data if isinstance(data, dict) else {},
                error=f"{response.status_code}: {message}",
                status_code=response.status_code,
            )

        if json_error is not None:
            return ApiResult(
                ok=False,
                status="INVALID_JSON",
                error=json_error,
                status_code=response.status_code,
            )
        if not isinstance(data, dict):
            return ApiResult(
                ok=False,
                status="INVALID_JSON",
                error="Backend JSON response is not an object",
                status_code=response.status_code,
            )
        return ApiResult(
            ok=True,
            status=_status_from_payload(data),
            data=data,
            status_code=response.status_code,
        )


def build_api_client(
    *,
    mode: str = API_MODE,
    base_url: str = API_BASE_URL,
    device_id: str = DEVICE_ID,
    timeout: float = REQUEST_TIMEOUT,
) -> KitungaApiClient:
    normalized_mode = mode.strip().lower()
    if normalized_mode == "mock":
        return MockApiClient(device_id=device_id)
    if normalized_mode == "real":
        return RealApiClient(base_url=base_url, device_id=device_id, timeout=timeout)
    raise ValueError("API_MODE must be 'mock' or 'real'")


def _normalize_uid(uid: str) -> str:
    return "".join(str(uid).strip().upper().split())


def _status_from_payload(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("status", "invoice_status", "session_status", "payment_status"):
        value = data.get(key)
        if value:
            return str(value).upper()
    return None


def _error_from_payload(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("error", "detail", "message"):
        value = data.get(key)
        if value:
            return str(value)
    return None
