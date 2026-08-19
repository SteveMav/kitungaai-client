from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

from config import (
    API_BASE_URL,
    API_MODE,
    DEVICE_ID,
    DEVICE_SECRET,
    MOCK_BASKET_ID,
    MOCK_CUSTOMER_ID,
    MOCK_CUSTOMER_NAME,
    REQUEST_TIMEOUT,
    SIMULATED_RFID_UID,
)

logger = logging.getLogger(__name__)


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
        basket_id: str,
        label: str,
        confidence: float,
        *,
        detection_id: str | None = None,
    ) -> ApiResult:
        ...

    def get_basket_status(self, basket_id: str) -> ApiResult:
        ...

    def confirm_rfid_payment(self, basket_id: str, rfid_uid: str) -> ApiResult:
        ...

    def acknowledge_reset(self, command_id: str) -> ApiResult:
        ...


class MockApiClient:
    """In-memory simulator for the Raspberry client workflow only."""

    def __init__(
        self,
        *,
        device_id: str = DEVICE_ID,
        known_rfid_uid: str = SIMULATED_RFID_UID,
        customer_name: str = MOCK_CUSTOMER_NAME,
        customer_id: str = MOCK_CUSTOMER_ID,
        basket_id: str = MOCK_BASKET_ID,
    ) -> None:
        self.device_id = device_id
        self.known_rfid_uid = _normalize_uid(known_rfid_uid)
        self.customer = {
            "id": customer_id,
            "name": customer_name,
            "display_name": customer_name,
        }
        self.default_basket_id = basket_id
        self._sessions: dict[str, dict[str, Any]] = {}

    def start_session(self, rfid_uid: str) -> ApiResult:
        normalized_uid = _normalize_uid(rfid_uid)
        if normalized_uid != self.known_rfid_uid:
            return ApiResult(
                ok=False,
                status="UNKNOWN_RFID",
                error="RFID card is not recognized by mock.",
            )

        session = {
            "basket_id": self.default_basket_id,
            "customer": dict(self.customer),
            "status": "ACTIVE",
            "detections": [],
            "items": {},
            "rfid_uid": normalized_uid,
        }
        self._sessions[self.default_basket_id] = session
        return ApiResult(
            ok=True,
            status="ACTIVE",
            data={
                "device_id": self.device_id,
                "basket_id": self.default_basket_id,
                "customer": dict(self.customer),
                "mock_items": _mock_items_payload(session),
                "status": "ACTIVE",
                "message": "Mock session started",
            },
        )

    def send_detection(
        self,
        basket_id: str,
        label: str,
        confidence: float,
        *,
        detection_id: str | None = None,
    ) -> ApiResult:
        session = self._sessions.get(basket_id)
        if session is None:
            return ApiResult(
                ok=False,
                status="NOT_FOUND",
                error=f"Mock basket not found: {basket_id}",
            )
        if session["status"] != "ACTIVE":
            return ApiResult(
                ok=False,
                status=session["status"],
                error=f"Mock basket is not active: {session['status']}",
            )

        detection = {
            "label": label,
            "confidence": round(float(confidence), 4),
            "accepted": True,
        }
        session["detections"].append(detection)
        items = session.setdefault("items", {})
        items[label] = int(items.get(label, 0)) + 1
        return ApiResult(
            ok=True,
            status="PRODUCT_ADDED",
            data={
                "basket_id": basket_id,
                "label": label,
                "confidence": detection["confidence"],
                "accepted": True,
                "mock_items": _mock_items_payload(session),
                "status": session["status"],
                "message": "Mock product accepted",
            },
        )

    def get_basket_status(self, basket_id: str) -> ApiResult:
        session = self._sessions.get(basket_id)
        if session is None:
            return ApiResult(
                ok=False,
                status="NOT_FOUND",
                error=f"Mock basket not found: {basket_id}",
            )

        return ApiResult(
            ok=True,
            status=session["status"],
            data={
                "basket_id": basket_id,
                "status": session["status"],
                "detections_count": len(session["detections"]),
                "mock_items": _mock_items_payload(session),
            },
        )

    def confirm_rfid_payment(self, basket_id: str, rfid_uid: str) -> ApiResult:
        session = self._sessions.get(basket_id)
        if session is None:
            return ApiResult(
                ok=False,
                status="NOT_FOUND",
                error=f"Mock basket not found: {basket_id}",
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
                error="Mock basket is no longer available for payment",
            )

        session["status"] = "PAID"
        return ApiResult(
            ok=True,
            status="PAID",
            data={
                "basket_id": basket_id,
                "status": "PAID",
                "payment_status": "PAID",
                "mock_items": _mock_items_payload(session),
                "message": "Mock RFID payment accepted",
            },
        )

    def acknowledge_reset(self, command_id: str) -> ApiResult:
        return ApiResult(ok=True, status="ACKNOWLEDGED", data={"command_id": command_id})

    def get_mock_basket(self, basket_id: str | None = None) -> dict[str, int]:
        session = self._sessions.get(basket_id or self.default_basket_id)
        if session is None:
            return {}
        return dict(session.get("items", {}))

    def reset_session(self, basket_id: str | None = None) -> None:
        if basket_id is None:
            self._sessions.clear()
            return
        self._sessions.pop(basket_id, None)

def _mock_items_payload(session: dict[str, Any]) -> list[dict[str, Any]]:
    items = session.get("items") or {}
    return [
        {"label": label, "quantity": int(quantity)}
        for label, quantity in items.items()
        if int(quantity) > 0
    ]


class RealApiClient:
    """HTTP client for the future Django contract."""

    START_SESSION_PATH = "/api/iot/sessions/start/"
    SEND_DETECTION_PATH = "/api/iot/baskets/{basket_id}/detections/"
    BASKET_STATUS_PATH = "/api/iot/baskets/{basket_id}/status/"
    CONFIRM_PAYMENT_PATH = "/api/iot/baskets/{basket_id}/rfid-payment/"
    ACK_RESET_PATH = "/api/v1/devices/{device_id}/commands/{command_id}/ack"

    def __init__(
        self,
        *,
        base_url: str = API_BASE_URL,
        device_id: str = DEVICE_ID,
        device_secret: str = DEVICE_SECRET,
        timeout: float = REQUEST_TIMEOUT,
        session: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.device_id = device_id
        self.device_secret = device_secret
        self.timeout = timeout
        self.session = session or requests.Session()
        self._pending_detection_keys: dict[tuple[str, str], str] = {}
        self._pending_payment_keys: dict[tuple[str, str], str] = {}

    def start_session(self, rfid_uid: str) -> ApiResult:
        return self._request(
            "POST",
            self.START_SESSION_PATH,
            json_data={
                "device_id": self.device_id,
                "rfid_uid": rfid_uid,
            },
        )

    def send_detection(
        self,
        basket_id: str,
        label: str,
        confidence: float,
        *,
        detection_id: str | None = None,
    ) -> ApiResult:
        request_key = (basket_id, detection_id or str(uuid.uuid4()))
        idempotency_key = self._pending_detection_keys.setdefault(request_key, str(uuid.uuid4()))
        result = self._request(
            "POST",
            self.SEND_DETECTION_PATH.format(basket_id=basket_id),
            json_data={
                "device_id": self.device_id,
                "label": label,
                "confidence": round(float(confidence), 4),
            },
            idempotency_key=idempotency_key,
        )
        if result.status_code is not None:
            self._pending_detection_keys.pop(request_key, None)
        return result

    def get_basket_status(self, basket_id: str) -> ApiResult:
        return self._request(
            "GET",
            self.BASKET_STATUS_PATH.format(basket_id=basket_id),
        )

    def confirm_rfid_payment(self, basket_id: str, rfid_uid: str) -> ApiResult:
        normalized_uid = _normalize_uid(rfid_uid)
        request_key = (basket_id, normalized_uid)
        idempotency_key = self._pending_payment_keys.setdefault(request_key, str(uuid.uuid4()))
        result = self._request(
            "POST",
            self.CONFIRM_PAYMENT_PATH.format(basket_id=basket_id),
            json_data={
                "device_id": self.device_id,
                "rfid_uid": normalized_uid,
            },
            idempotency_key=idempotency_key,
        )
        if result.status_code is not None:
            self._pending_payment_keys.pop(request_key, None)
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
        if not self.device_secret:
            return ApiResult(
                ok=False,
                status="DEVICE_SECRET_MISSING",
                error="DEVICE_SECRET is missing. Add the provisioned device secret to .env and restart the Pi client.",
            )
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json", "X-Device-Code": self.device_id}
        if self.device_secret:
            headers["Authorization"] = f"Device {self.device_secret}"
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
                    error="Device authentication was rejected (401). Verify DEVICE_ID and DEVICE_SECRET in .env, then restart the Pi client.",
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
    for key in ("status", "session_status", "basket_status", "payment_status"):
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
