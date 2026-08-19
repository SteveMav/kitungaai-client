from __future__ import annotations

import argparse
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import cv2
import numpy as np

from api_client import ApiResult, build_api_client
from camera import CameraManager, capture_image
from config import (
    API_BASE_URL,
    API_MODE,
    BASKET_STATUS_POLL_SECONDS,
    BUZZER_PIN,
    CAMERA_BACKEND,
    CAMERA_INDEX,
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    CONFIDENCE_THRESHOLD,
    COOLDOWN_SECONDS,
    DETECTION_DISAPPEAR_FRAMES,
    DETECTION_STABILITY_FRAMES,
    DEVICE_ID,
    HARDWARE_ENABLED,
    LOG_FILE,
    LOG_LEVEL,
    MATRIX_CASCADED,
    MATRIX_DEVICE,
    MATRIX_ENABLED,
    MATRIX_INTENSITY,
    MATRIX_REVERSE_ORDER,
    MATRIX_SPEED_HZ,
    MODEL_PATH,
    PIR_ACTIVE_HIGH,
    PIR_PIN,
    PRESENCE_GRACE_SECONDS,
    PREVIEW_ENABLED,
    PREVIEW_HOST,
    PREVIEW_PORT,
    REQUEST_TIMEOUT,
    RFID_MODE,
    SCAN_INTERVAL_SECONDS,
    SIMULATED_RFID_INTERVAL_SECONDS,
    SIMULATED_RFID_UID,
    TEST_IMAGE_PATH,
    TRACK_IOU_THRESHOLD,
)
from deduplication import ProductDeduplicator
from detector import DetectionResult, YoloObjectDetector
from hardware import HardwareConfig, HardwareController
from iot_state import LocalDeviceState, SessionStatus
from presence import PresenceDetectionWindow
from preview import PreviewServer
from rfid import build_rfid_reader


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kitunga AI Raspberry Pi IoT client")
    parser.add_argument("--api-mode", default=API_MODE, choices=["mock", "real"])
    parser.add_argument("--api-base-url", default=API_BASE_URL)
    parser.add_argument("--device-id", default=DEVICE_ID)
    parser.add_argument("--request-timeout", type=float, default=REQUEST_TIMEOUT)
    parser.add_argument("--rfid-mode", default=RFID_MODE, choices=["simulation", "hardware"])
    parser.add_argument("--simulated-rfid-uid", default=SIMULATED_RFID_UID)
    parser.add_argument(
        "--simulated-rfid-interval",
        type=float,
        default=SIMULATED_RFID_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--camera-backend",
        default=CAMERA_BACKEND,
        choices=["auto", "picamera2", "libcamera", "opencv"],
    )
    parser.add_argument("--camera-index", type=int, default=CAMERA_INDEX)
    parser.add_argument("--capture-width", type=int, default=CAPTURE_WIDTH)
    parser.add_argument("--capture-height", type=int, default=CAPTURE_HEIGHT)
    parser.add_argument("--model-path", default=str(MODEL_PATH))
    parser.add_argument("--test-image", default=TEST_IMAGE_PATH)
    parser.add_argument(
        "--simulate-detection",
        default="",
        help="Comma-separated labels to simulate, for example ESP32,Arduino",
    )
    parser.add_argument("--simulate-confidence", type=float, default=0.95)
    parser.add_argument("--threshold", type=float, default=CONFIDENCE_THRESHOLD)
    parser.add_argument("--stability-frames", type=int, default=DETECTION_STABILITY_FRAMES)
    parser.add_argument("--cooldown", type=float, default=COOLDOWN_SECONDS)
    parser.add_argument("--disappear-frames", type=int, default=DETECTION_DISAPPEAR_FRAMES)
    parser.add_argument(
        "--presence-grace-seconds",
        type=float,
        default=PRESENCE_GRACE_SECONDS,
    )
    parser.add_argument(
        "--track-iou-threshold",
        type=float,
        default=TRACK_IOU_THRESHOLD,
    )
    parser.add_argument("--interval", type=float, default=SCAN_INTERVAL_SECONDS)
    parser.add_argument("--basket-poll-interval", type=float, default=BASKET_STATUS_POLL_SECONDS)
    parser.add_argument("--once", action="store_true", help="Stop after one paid mock/real session")
    parser.add_argument("--no-send", action="store_true", help="Run detection without API product calls")
    parser.add_argument("--no-preview", action="store_true")
    return parser.parse_args()


def configure_logging() -> None:
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                LOG_FILE,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
        )
    except Exception as exc:
        logging.warning("Could not initialize file logging at %s: %s", LOG_FILE, exc)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def build_hardware() -> HardwareController:
    return HardwareController(
        HardwareConfig(
            enabled=HARDWARE_ENABLED,
            pir_pin=PIR_PIN,
            pir_active_high=PIR_ACTIVE_HIGH,
            buzzer_pin=BUZZER_PIN,
            matrix_enabled=MATRIX_ENABLED,
            matrix_device=MATRIX_DEVICE,
            matrix_intensity=MATRIX_INTENSITY,
            matrix_speed_hz=MATRIX_SPEED_HZ,
            matrix_cascaded=MATRIX_CASCADED,
            matrix_reverse_order=MATRIX_REVERSE_ORDER,
        )
    )


def main() -> None:
    configure_logging()
    args = parse_args()
    logger = logging.getLogger("kitunga_pi_client")
    logger.info("Kitunga IoT client starting in API_MODE=%s", args.api_mode)

    state = LocalDeviceState(device_id=args.device_id)
    api = build_api_client(
        mode=args.api_mode,
        base_url=args.api_base_url,
        device_id=args.device_id,
        timeout=args.request_timeout,
    )
    rfid = build_rfid_reader(
        mode=args.rfid_mode,
        simulated_uid=args.simulated_rfid_uid,
        simulated_interval_seconds=args.simulated_rfid_interval,
    )
    deduplicator = ProductDeduplicator(
        confidence_threshold=args.threshold,
        stability_frames=args.stability_frames,
        cooldown_seconds=args.cooldown,
        disappear_frames=args.disappear_frames,
        track_iou_threshold=args.track_iou_threshold,
    )
    presence_window = PresenceDetectionWindow(
        grace_seconds=args.presence_grace_seconds,
    )

    hardware = build_hardware()
    preview = PreviewServer()
    if PREVIEW_ENABLED and not args.no_preview:
        preview.start(host=PREVIEW_HOST, port=PREVIEW_PORT)

    detector = _build_detector(args, logger)
    camera = _build_camera(args, logger)
    if detector is None and not args.simulate_detection:
        hardware.show_error()
        hardware.beep_error()
        hardware.close()
        return
    if camera is None and not args.test_image and not args.simulate_detection:
        hardware.show_error()
        hardware.beep_error()
        hardware.close()
        return

    last_status_poll = 0.0
    hardware.show_waiting()
    preview.update(frame=None, detection=None, state=state)

    try:
        while True:
            try:
                if state.session_status is SessionStatus.WAITING_CUSTOMER:
                    _handle_waiting_customer(
                        api=api,
                        rfid=rfid,
                        state=state,
                        hardware=hardware,
                        preview=preview,
                        logger=logger,
                    )
                    last_status_poll = 0.0

                elif state.session_status is SessionStatus.RFID_ENROLLMENT_PENDING:
                    _handle_rfid_enrollment_pending(
                        api=api,
                        rfid=rfid,
                        state=state,
                        hardware=hardware,
                        preview=preview,
                        logger=logger,
                    )

                elif state.session_status is SessionStatus.ACTIVE:
                    last_status_poll = _handle_active_session(
                        args=args,
                        api=api,
                        rfid=rfid,
                        detector=detector,
                        camera=camera,
                        state=state,
                        hardware=hardware,
                        preview=preview,
                        deduplicator=deduplicator,
                        presence_window=presence_window,
                        last_status_poll=last_status_poll,
                        logger=logger,
                    )

                elif state.session_status is SessionStatus.CHECKOUT_PENDING:
                    last_status_poll = _handle_checkout_pending(
                        args=args,
                        api=api,
                        rfid=rfid,
                        state=state,
                        hardware=hardware,
                        preview=preview,
                        last_status_poll=last_status_poll,
                        logger=logger,
                    )

                elif state.session_status is SessionStatus.PAYMENT_SUCCESS:
                    time.sleep(1.2)
                    if state.reset_command_id:
                        acknowledgement = api.acknowledge_reset(state.reset_command_id)
                        state.mark_api_result(ok=acknowledgement.ok, error=acknowledgement.error)
                        if not acknowledgement.ok:
                            logger.warning(
                                "Reset acknowledgement failed: %s",
                                acknowledgement.error or acknowledgement.status,
                            )
                            preview.update(frame=None, detection=None, state=state)
                            continue
                    logger.info("Session paid; resetting local IoT state.")
                    _reset_mock_api_session(api)
                    state.reset_session()
                    deduplicator.reset()
                    presence_window.reset()
                    hardware.show_waiting()
                    preview.update(frame=None, detection=None, state=state)
                    if args.once:
                        break
            except Exception as exc:
                logger.exception("Cycle failed: %s", exc)
                state.last_error = str(exc)
                hardware.show_error()
                hardware.beep_error()
                preview.update(frame=None, detection=None, state=state)

            time.sleep(args.interval)

    except KeyboardInterrupt:
        logger.info("Stopped by user.")
    finally:
        if camera is not None:
            camera.release()
        hardware.close()


def _build_detector(args: argparse.Namespace, logger: logging.Logger) -> YoloObjectDetector | None:
    if args.simulate_detection:
        logger.info("YOLO bypass enabled with simulated label=%s", args.simulate_detection)
        return None

    try:
        return YoloObjectDetector(args.model_path)
    except Exception as exc:
        logger.error("Detector initialization failed: %s", exc)
        return None


def _build_camera(args: argparse.Namespace, logger: logging.Logger) -> CameraManager | None:
    if args.simulate_detection or args.test_image:
        return None

    try:
        camera = CameraManager(
            camera_index=args.camera_index,
            camera_backend=args.camera_backend,
            width=args.capture_width,
            height=args.capture_height,
        )
    except Exception as exc:
        logger.error("Camera initialization failed: %s", exc)
        return None

    logger.info("Camera opened with backend=%s", camera.backend)
    return camera


def _handle_waiting_customer(
    *,
    api,
    rfid,
    state: LocalDeviceState,
    hardware: HardwareController,
    preview: PreviewServer,
    logger: logging.Logger,
) -> None:
    uid = rfid.read_uid()
    if not uid:
        preview.update(frame=None, detection=None, state=state)
        return

    logger.info("RFID card read for session start.")
    result = api.start_session(uid)
    state.mark_api_result(ok=result.ok, error=result.error)
    if not result.ok:
        logger.warning("Session start rejected: %s", _api_error_message(result))
        hardware.show_error()
        hardware.beep_error()
        preview.update(frame=None, detection=None, state=state)
        return

    if _status(result) == "RFID_ENROLLMENT_PENDING":
        state.mark_rfid_enrollment_pending()
        logger.info("Unknown RFID card sent for administrator approval.")
        hardware.show_rfid_enrollment_pending()
        preview.update(frame=None, detection=None, state=state)
        return

    customer = _extract_customer(result)
    state.start_session(customer=customer)
    _sync_mock_items(state, result)
    logger.info("Customer identified: %s", state.preview_payload().get("customer") or "-")
    hardware.show_client_identified()
    preview.update(frame=None, detection=None, state=state)


def _handle_rfid_enrollment_pending(
    *,
    api,
    rfid,
    state: LocalDeviceState,
    hardware: HardwareController,
    preview: PreviewServer,
    logger: logging.Logger,
) -> None:
    """Wait for approval, then activate only after the card is presented again."""
    preview.update(frame=None, detection=None, state=state)
    uid = rfid.read_uid()
    if not uid:
        return

    logger.info("RFID card read while enrollment is pending.")
    result = api.start_session(uid)
    state.mark_api_result(ok=result.ok, error=result.error)
    if not result.ok:
        logger.warning("RFID enrollment check rejected: %s", _api_error_message(result))
        if _status(result) == "RFID_ENROLLMENT_REJECTED":
            state.reset_session()
            hardware.show_error()
            hardware.beep_error()
        preview.update(frame=None, detection=None, state=state)
        return

    if _status(result) == "RFID_ENROLLMENT_PENDING":
        hardware.show_rfid_enrollment_pending()
        preview.update(frame=None, detection=None, state=state)
        return

    state.start_session(customer=_extract_customer(result))
    _sync_mock_items(state, result)
    logger.info("Approved RFID card activated a new invoice.")
    hardware.show_client_identified()
    preview.update(frame=None, detection=None, state=state)


def _handle_active_session(
    *,
    args: argparse.Namespace,
    api,
    rfid=None,
    detector: YoloObjectDetector | None,
    camera: CameraManager | None,
    state: LocalDeviceState,
    hardware: HardwareController,
    preview: PreviewServer,
    deduplicator: ProductDeduplicator,
    presence_window: PresenceDetectionWindow,
    last_status_poll: float,
    logger: logging.Logger,
) -> float:
    if rfid is not None and _handle_rfid_payment_scan(
        api=api,
        rfid=rfid,
        state=state,
        hardware=hardware,
        preview=preview,
        logger=logger,
    ):
        return last_status_poll

    presence = hardware.presence_detected()
    hardware.apply_presence(presence)
    detection_active = presence_window.observe(presence)

    if detection_active:
        detections, frame = _read_detection(args, detector, camera)
        preview.update(
            frame=frame,
            detections=detections,
            state=state,
            presence_detected=presence,
            detection_active=detection_active,
        )
        candidates = deduplicator.observe(detections)
        for candidate in candidates:
            _send_product_candidate(
                api=api,
                args=args,
                state=state,
                hardware=hardware,
                deduplicator=deduplicator,
                track_id=candidate.track_id,
                label=candidate.label,
                confidence=candidate.confidence,
                logger=logger,
            )
    else:
        preview.update(
            frame=None,
            detections=None,
            state=state,
            presence_detected=presence,
            detection_active=detection_active,
        )

    now = time.monotonic()
    if now - last_status_poll >= args.basket_poll_interval:
        _poll_basket_status(api=api, state=state, hardware=hardware, logger=logger)
        return now
    return last_status_poll


def _handle_checkout_pending(
    *,
    args: argparse.Namespace,
    api,
    rfid,
    state: LocalDeviceState,
    hardware: HardwareController,
    preview: PreviewServer,
    last_status_poll: float,
    logger: logging.Logger,
) -> float:
    preview.update(frame=None, detection=None, state=state)
    now = time.monotonic()
    if now - last_status_poll >= args.basket_poll_interval:
        _poll_basket_status(api=api, state=state, hardware=hardware, logger=logger)
        if state.session_status is not SessionStatus.CHECKOUT_PENDING:
            preview.update(frame=None, detection=None, state=state)
            return now
        last_status_poll = now

    _handle_rfid_payment_scan(
        api=api,
        rfid=rfid,
        state=state,
        hardware=hardware,
        preview=preview,
        logger=logger,
    )
    return last_status_poll


def _handle_rfid_payment_scan(
    *,
    api,
    rfid,
    state: LocalDeviceState,
    hardware: HardwareController,
    preview: PreviewServer,
    logger: logging.Logger,
) -> bool:
    """Use a new RFID presentation to pay the currently active basket."""
    uid = rfid.read_uid()
    if not uid:
        return False

    logger.info("RFID card read for payment confirmation.")
    result = api.confirm_rfid_payment(uid)
    state.mark_api_result(ok=result.ok, error=result.error)
    _sync_mock_items(state, result)
    if result.ok and _status(result) == "PAID":
        logger.info("Invoice payment confirmed.")
        reset_command_id = result.data.get("reset_command_id")
        state.mark_payment_success(
            reset_command_id=str(reset_command_id) if reset_command_id else None,
        )
        hardware.show_payment_success()
        hardware.beep_payment_success()
    else:
        logger.warning("Payment confirmation failed: %s", _api_error_message(result))
        hardware.show_error()
        hardware.beep_error()
    preview.update(frame=None, detection=None, state=state)
    return True


def _read_detection(
    args: argparse.Namespace,
    detector: YoloObjectDetector | None,
    camera: CameraManager | None,
) -> tuple[tuple[DetectionResult, ...], np.ndarray | None]:
    if args.simulate_detection:
        frame = np.zeros((480, 640, 3), np.uint8) + 45
        labels = tuple(
            label.strip()
            for label in args.simulate_detection.split(",")
            if label.strip()
        )
        detections = []
        for index, label in enumerate(labels):
            column, row = index % 3, index // 3
            x1, y1 = 40 + column * 200, 80 + row * 170
            bbox = (x1, y1, x1 + 150, y1 + 120)
            cv2.rectangle(frame, bbox[:2], bbox[2:], (0, 255, 204), 2)
            detections.append(
                DetectionResult(
                    label=label,
                    confidence=args.simulate_confidence,
                    bbox_xyxy=bbox,
                )
            )
        return tuple(detections), frame

    if detector is None:
        raise RuntimeError("Detector is not initialized.")

    if args.test_image:
        image_path = capture_image(test_image_path=Path(args.test_image))
        frame = cv2.imread(str(image_path))
        return detector.detect(image_path), frame

    if camera is None:
        raise RuntimeError("Camera is not initialized.")

    if camera.is_streaming:
        frame = camera.get_frame()
        if frame is None:
            raise RuntimeError("Camera did not return an image.")
        return detector.detect_frame(frame), frame

    image_path = camera.capture_image()
    frame = cv2.imread(str(image_path))
    return detector.detect(image_path), frame


def _send_product_candidate(
    *,
    api,
    args: argparse.Namespace,
    state: LocalDeviceState,
    hardware: HardwareController,
    deduplicator: ProductDeduplicator,
    track_id: str,
    label: str,
    confidence: float,
    logger: logging.Logger,
) -> None:
    logger.info(
        "Stable product candidate: track=%s label=%s confidence=%.2f",
        track_id,
        label,
        confidence,
    )
    if args.no_send:
        logger.info("No-send mode enabled; product not sent to API.")
        return

    result = api.send_detection(label, confidence, detection_id=track_id)
    state.mark_api_result(ok=result.ok, error=result.error)
    if not result.ok:
        logger.warning("Product send failed: %s", _api_error_message(result))
        hardware.show_error()
        hardware.beep_error()
        return

    deduplicator.mark_accepted(track_id)
    _sync_mock_items(state, result)
    display_label = str(result.data.get("display_label") or label)
    state.mark_detection(label=display_label, confidence=confidence)
    logger.info("Product accepted by API/mock: %s → %s %.2f", label, display_label, confidence)
    hardware.show_detection(display_label, confidence)
    hardware.beep_detection()


def _poll_basket_status(
    *,
    api,
    state: LocalDeviceState,
    hardware: HardwareController,
    logger: logging.Logger,
) -> None:
    result = api.get_invoice_status()
    state.mark_api_result(ok=result.ok, error=result.error)
    if not result.ok:
        logger.warning("Basket status polling failed: %s", _api_error_message(result))
        hardware.show_error()
        return

    status = _status(result)
    _sync_mock_items(state, result)
    logger.debug("Basket status: %s", status)
    if status == "CHECKOUT_PENDING":
        state.mark_checkout_pending()
        hardware.show_checkout_pending()
        logger.info("Basket moved to CHECKOUT_PENDING.")
    elif status == "PAID":
        reset_command_id = result.data.get("reset_command_id")
        if not reset_command_id:
            logger.warning("Paid basket has no reset command available yet.")
            return
        state.mark_payment_success(reset_command_id=str(reset_command_id))
        hardware.show_payment_success()
        hardware.beep_payment_success()
        logger.info("Basket payment was confirmed manually; resetting device.")


def _sync_mock_items(state: LocalDeviceState, result: ApiResult) -> None:
    if "mock_items" in result.data:
        state.update_mock_items(result.data.get("mock_items"))


def _reset_mock_api_session(api) -> None:
    reset_session = getattr(api, "reset_session", None)
    if callable(reset_session):
        reset_session()


def _extract_customer(result: ApiResult) -> dict | None:
    customer = result.data.get("customer")
    if isinstance(customer, dict):
        return customer
    if customer:
        return {"display_name": str(customer)}
    return None


def _status(result: ApiResult) -> str | None:
    if result.status:
        return result.status.upper()
    for key in ("status", "invoice_status", "session_status", "payment_status"):
        value = result.data.get(key)
        if value:
            return str(value).upper()
    return None


def _api_error_message(result: ApiResult) -> str:
    if result.status == "DEVICE_UNAUTHORIZED":
        return "Identifiant appareil refusé (401). Vérifiez DEVICE_ID et activez la Raspberry dans Django."
    if result.status == "API_ROUTE_NOT_FOUND":
        return "Route backend introuvable (404). Redémarrez Django mis à jour et vérifiez API_BASE_URL."
    return result.error or result.status or "Erreur API inconnue"


if __name__ == "__main__":
    main()
