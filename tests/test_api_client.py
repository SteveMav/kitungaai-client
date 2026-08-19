from __future__ import annotations

import unittest

import requests

from api_client import MockApiClient, RealApiClient


class MockApiClientTest(unittest.TestCase):
    def test_full_mock_flow(self) -> None:
        client = MockApiClient(
            known_rfid_uid="04A732B19C",
            basket_id="KITUNGA-0042",
        )

        started = client.start_session("04A732B19C")
        self.assertTrue(started.ok)
        self.assertEqual(started.status, "ACTIVE")
        self.assertEqual(started.data["basket_id"], "KITUNGA-0042")
        self.assertEqual(started.data["customer"]["display_name"], "Monsieur X")

        added = client.send_detection("KITUNGA-0042", "ESP32", 0.96)
        self.assertTrue(added.ok)
        self.assertEqual(added.status, "PRODUCT_ADDED")

        status = client.get_basket_status("KITUNGA-0042")
        self.assertTrue(status.ok)
        self.assertEqual(status.status, "ACTIVE")

        paid = client.confirm_rfid_payment("KITUNGA-0042", "04A732B19C")
        self.assertTrue(paid.ok)
        self.assertEqual(paid.status, "PAID")

    def test_mock_basket_counts_and_resets(self) -> None:
        client = MockApiClient(
            known_rfid_uid="04A732B19C",
            basket_id="KITUNGA-0042",
        )

        started = client.start_session("04A732B19C")
        self.assertTrue(started.ok)
        self.assertEqual(client.get_mock_basket("KITUNGA-0042"), {})

        added = client.send_detection("KITUNGA-0042", "ESP32", 0.96)
        self.assertTrue(added.ok)
        self.assertEqual(client.get_mock_basket("KITUNGA-0042"), {"ESP32": 1})
        self.assertEqual(added.data["mock_items"], [{"label": "ESP32", "quantity": 1}])

        added_again = client.send_detection("KITUNGA-0042", "ESP32", 0.97)
        self.assertTrue(added_again.ok)
        self.assertEqual(client.get_mock_basket("KITUNGA-0042"), {"ESP32": 2})
        self.assertEqual(
            added_again.data["mock_items"],
            [{"label": "ESP32", "quantity": 2}],
        )

        status = client.get_basket_status("KITUNGA-0042")
        self.assertTrue(status.ok)
        self.assertEqual(status.status, "ACTIVE")

        client.reset_session("KITUNGA-0042")
        self.assertEqual(client.get_mock_basket("KITUNGA-0042"), {})

    def test_mock_accepts_all_objects_seen_in_one_camera_cycle_before_rfid_payment(self) -> None:
        client = MockApiClient(
            known_rfid_uid="04A732B19C",
        )
        client.start_session("04A732B19C")

        for label in ("ESP32", "Arduino", "ESP32"):
            result = client.send_detection("KITUNGA-0042", label, 0.95)
            self.assertTrue(result.ok)

        self.assertEqual(client.get_mock_basket("KITUNGA-0042"), {"ESP32": 2, "Arduino": 1})
        self.assertEqual(client.get_basket_status("KITUNGA-0042").status, "ACTIVE")
        self.assertTrue(client.confirm_rfid_payment("KITUNGA-0042", "04A732B19C").ok)


class _InvalidJsonResponse:
    status_code = 200
    reason = "OK"

    def json(self):
        raise ValueError("invalid json")


class _HttpErrorResponse:
    status_code = 500
    reason = "Server Error"

    def json(self):
        return {"status": "ERROR", "message": "broken"}


class _UnauthorizedResponse:
    status_code = 401
    reason = "Unauthorized"

    def json(self):
        return {"status": "DEVICE_UNAUTHORIZED", "message": "Device authentication failed."}


class _UnknownRouteResponse:
    status_code = 404
    reason = "Not Found"

    def json(self):
        raise ValueError("not json")


class _FakeSession:
    def __init__(self, response) -> None:
        self.response = response
        self.calls = []

    def request(self, *_args, **_kwargs):
        self.calls.append(_kwargs)
        return self.response


class _ConnectionErrorSession:
    def __init__(self) -> None:
        self.calls = []

    def request(self, *_args, **_kwargs):
        self.calls.append(_kwargs)
        raise requests.ConnectionError("offline")


class RealApiClientTest(unittest.TestCase):
    def test_invalid_json_is_reported(self) -> None:
        client = RealApiClient(
            base_url="http://backend",
            device_secret="device-secret",
            session=_FakeSession(_InvalidJsonResponse()),
        )
        result = client.get_basket_status("KITUNGA-0042")
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "INVALID_JSON")

    def test_http_error_is_reported(self) -> None:
        client = RealApiClient(
            base_url="http://backend",
            device_secret="device-secret",
            session=_FakeSession(_HttpErrorResponse()),
        )
        result = client.get_basket_status("KITUNGA-0042")
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "ERROR")
        self.assertIn("500", result.error or "")

    def test_device_requests_include_identity_and_idempotency_key(self) -> None:
        session = _FakeSession(_HttpErrorResponse())
        client = RealApiClient(
            base_url="http://backend",
            device_id="KITUNGA-PI-001",
            device_secret="device-secret",
            session=session,
        )
        client.send_detection("basket-1", "ESP32", 0.95)
        headers = session.calls[0]["headers"]
        self.assertEqual(headers["Authorization"], "Device device-secret")
        self.assertEqual(headers["X-Device-Code"], "KITUNGA-PI-001")
        self.assertIn("Idempotency-Key", headers)

    def test_each_tracked_object_has_its_own_retry_key(self) -> None:
        session = _ConnectionErrorSession()
        client = RealApiClient(
            base_url="http://backend",
            device_secret="device-secret",
            session=session,
        )

        client.send_detection("basket-1", "ESP32", 0.95, detection_id="track-a")
        client.send_detection("basket-1", "ESP32", 0.95, detection_id="track-a")
        client.send_detection("basket-1", "ESP32", 0.95, detection_id="track-b")

        keys = [call["headers"]["Idempotency-Key"] for call in session.calls]
        self.assertEqual(keys[0], keys[1])
        self.assertNotEqual(keys[0], keys[2])

    def test_missing_device_secret_fails_before_network_request(self) -> None:
        session = _FakeSession(_HttpErrorResponse())
        client = RealApiClient(base_url="http://backend", device_secret="", session=session)
        result = client.start_session("04A732B19C")
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "DEVICE_SECRET_MISSING")
        self.assertEqual(session.calls, [])

    def test_401_and_unknown_404_are_explained_for_the_pi_operator(self) -> None:
        unauthorized = RealApiClient(
            base_url="http://backend",
            device_secret="device-secret",
            session=_FakeSession(_UnauthorizedResponse()),
        ).start_session("04A732B19C")
        self.assertEqual(unauthorized.status, "DEVICE_UNAUTHORIZED")
        self.assertIn("401", unauthorized.error or "")

        route_not_found = RealApiClient(
            base_url="http://backend",
            device_secret="device-secret",
            session=_FakeSession(_UnknownRouteResponse()),
        ).start_session("04A732B19C")
        self.assertEqual(route_not_found.status, "API_ROUTE_NOT_FOUND")
        self.assertIn("404", route_not_found.error or "")


if __name__ == "__main__":
    unittest.main()
