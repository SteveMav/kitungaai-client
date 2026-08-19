from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from typing import Any

import cv2
import numpy as np

from detector import DetectionResult
from iot_state import LocalDeviceState

logger = logging.getLogger(__name__)


class PreviewServer:
    def __init__(self) -> None:
        self._frame: np.ndarray | None = None
        self._status: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self, *, host: str, port: int) -> bool:
        try:
            from flask import Flask, Response, jsonify, render_template_string
        except ImportError:
            logger.warning("Flask is not installed; preview server disabled.")
            return False

        app = Flask("kitunga_web_preview")

        @app.route("/")
        def index():
            return render_template_string(_HTML)

        @app.route("/video_feed")
        def video_feed():
            return Response(
                self._generate_frames(),
                mimetype="multipart/x-mixed-replace; boundary=frame",
            )

        @app.route("/status.json")
        def status_json():
            with self._lock:
                payload = dict(self._status)
            return jsonify(payload)

        def run() -> None:
            logging.getLogger("werkzeug").setLevel(logging.ERROR)
            app.run(host=host, port=port, debug=False, threaded=True)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        logger.info("Preview Flask server started on http://%s:%s", host, port)
        return True

    def update(
        self,
        *,
        frame: np.ndarray | None,
        state: LocalDeviceState,
        detection: DetectionResult | None = None,
        detections: Iterable[DetectionResult] | None = None,
        presence_detected: bool | None = None,
        detection_active: bool | None = None,
    ) -> None:
        status = state.preview_payload()
        if presence_detected is not None:
            status["presence_detected"] = presence_detected
        if detection_active is not None:
            status["detection_active"] = detection_active
        visible_detections = (
            tuple(detections)
            if detections is not None
            else (() if detection is None else (detection,))
        )
        status["detections"] = [
            {
                "label": detected.label,
                "confidence": round(detected.confidence, 2),
            }
            for detected in visible_detections
            if detected.found
        ]
        status["visible_detections"] = len(status["detections"])

        annotated = None
        if frame is not None:
            annotated = frame.copy()
            _draw_detections(annotated, visible_detections)
            _draw_status(annotated, status)

        with self._lock:
            if annotated is not None:
                self._frame = annotated
            self._status = status

    def _generate_frames(self):
        while True:
            time.sleep(0.04)
            with self._lock:
                frame = None if self._frame is None else self._frame.copy()
                status = dict(self._status)

            if frame is None:
                frame = _placeholder(status)

            ok, buffer = cv2.imencode(".jpg", frame)
            if ok:
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                    + buffer.tobytes()
                    + b"\r\n"
                )


def _placeholder(status: dict[str, Any]) -> np.ndarray:
    image = np.zeros((480, 640, 3), np.uint8) + 35
    _draw_status(image, status or {"session_status": "WAITING_CUSTOMER"})
    cv2.putText(
        image,
        "Kitunga-AI preview",
        (150, 235),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 204),
        2,
    )
    return image


def _draw_detections(frame: np.ndarray, detections: Iterable[DetectionResult]) -> None:
    for index, detection in enumerate(detections):
        if not detection.found:
            continue

        label = detection.label or "unknown"
        confidence = detection.confidence
        if detection.bbox_xyxy is not None:
            x1, y1, x2, y2 = detection.bbox_xyxy
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 204), 2)
            text_origin = (max(0, x1), max(20, y1 - 8))
        else:
            text_origin = (16, 70 + index * 28)

        cv2.putText(
            frame,
            f"{label} {confidence:.2f}",
            text_origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 204),
            2,
        )


def _draw_status(frame: np.ndarray, status: dict[str, Any]) -> None:
    lines = [
        f"device: {status.get('device_id') or '-'}",
        f"client: {status.get('customer') or '-'}",
        f"basket: {status.get('basket_id') or '-'}",
        f"session: {status.get('session_status') or '-'}",
        f"vision: {'ON' if status.get('detection_active') else 'OFF'}",
        f"backend: {'OK' if status.get('backend_available', True) else 'DOWN'}",
    ]
    if status.get("last_label"):
        confidence = status.get("last_confidence")
        if isinstance(confidence, (int, float)):
            lines.append(f"last: {status['last_label']} {confidence:.2f}")
        else:
            lines.append(f"last: {status['last_label']}")
    if status.get("last_error"):
        lines.append(f"error: {status['last_error']}")
    mock_items = status.get("mock_items") or []
    if mock_items:
        lines.append("items:")
        for item in mock_items[:4]:
            label = item.get("label") if isinstance(item, dict) else None
            quantity = item.get("quantity") if isinstance(item, dict) else None
            lines.append(f"- {label or '-'} x{quantity or 0}")

    x, y = 12, 22
    line_height = 21
    width = min(frame.shape[1] - 24, 480)
    height = line_height * len(lines) + 10
    cv2.rectangle(frame, (6, 4), (6 + width, 4 + height), (20, 20, 20), -1)
    cv2.rectangle(frame, (6, 4), (6 + width, 4 + height), (0, 255, 204), 1)

    for index, line in enumerate(lines):
        color = (0, 255, 204)
        if line.startswith("error:") or line == "backend: DOWN":
            color = (0, 80, 255)
        cv2.putText(
            frame,
            line[:72],
            (x, y + index * line_height),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            1,
        )


_HTML = """
<html>
    <head>
        <title>Kitunga-AI - Live Preview</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; background: #121212; color: white; padding-top: 24px; }
            h1 { color: #00ffcc; margin-bottom: 4px; }
            .container { margin: 18px auto; max-width: 880px; background: #1e1e1e; padding: 14px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
            img { border: 2px solid #00ffcc; border-radius: 6px; width: 100%; height: auto; background: #000; }
            .status { font-weight: bold; color: #a0a0a0; margin-top: 12px; }
            .panel { text-align: left; margin-top: 14px; color: #f4f4f4; line-height: 1.55; }
            .panel strong { color: #00ffcc; }
            .panel ul { margin: 6px 0 0 0; padding-left: 18px; }
        </style>
    </head>
    <body>
        <h1>KITUNGA-AI</h1>
        <h3>Preview technique Raspberry Pi</h3>
        <div class="container">
            <img src="/video_feed" alt="Flux video">
            <div class="status">Flux camera, detections YOLO et etat local</div>
            <div class="panel">
                <div><strong>Client :</strong> <span id="customer">-</span></div>
                <div><strong>Panier :</strong> <span id="basket">-</span></div>
                <div><strong>Etat :</strong> <span id="session">-</span></div>
                <div><strong>Dernier objet envoye :</strong> <span id="last-label">-</span></div>
                <div><strong>Detections a l'ecran :</strong></div>
                <ul id="detections"><li>Aucune detection</li></ul>
            </div>
        </div>
        <script>
            async function refreshStatus() {
                try {
                    const response = await fetch("/status.json", { cache: "no-store" });
                    const status = await response.json();
                    document.getElementById("customer").textContent = status.customer || "-";
                    document.getElementById("basket").textContent = status.basket_id || "-";
                    document.getElementById("session").textContent = status.session_status || "-";
                    document.getElementById("last-label").textContent = status.last_label || "-";

                    const list = document.getElementById("detections");
                    const detections = Array.isArray(status.detections) ? status.detections : [];
                    list.innerHTML = "";
                    if (detections.length === 0) {
                        const item = document.createElement("li");
                        item.textContent = "Aucune detection";
                        list.appendChild(item);
                        return;
                    }

                    for (const detection of detections) {
                        const item = document.createElement("li");
                        const confidence = Number(detection.confidence);
                        const suffix = Number.isFinite(confidence) ? ` (${Math.round(confidence * 100)}%)` : "";
                        item.textContent = `${detection.label || "Objet non identifie"}${suffix}`;
                        list.appendChild(item);
                    }
                } catch (_error) {
                    document.getElementById("session").textContent = "PREVIEW_ERROR";
                }
            }
            refreshStatus();
            setInterval(refreshStatus, 1000);
        </script>
    </body>
</html>
"""
