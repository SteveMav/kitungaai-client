from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2

from api_client import build_api_client
from camera import CameraManager, capture_image
from config import (
    API_BASE_URL,
    API_MODE,
    BUZZER_ACTIVE_HIGH,
    BUZZER_FREQUENCY_HZ,
    BUZZER_PIN,
    BUZZER_TYPE,
    CAMERA_BACKEND,
    CAMERA_INDEX,
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    DEVICE_ID,
    HARDWARE_ENABLED,
    MATRIX_CASCADED,
    MATRIX_DEVICE,
    MATRIX_ENABLED,
    MATRIX_INTENSITY,
    MATRIX_REVERSE_ORDER,
    MATRIX_SPEED_HZ,
    MODEL_PATH,
    PIR_ACTIVE_HIGH,
    PIR_PIN,
    REQUEST_TIMEOUT,
    RFID_ABSENT_READS_TO_REARM,
    RFID_MODE,
    RFID_RST_PIN,
    RFID_SPI_BUS,
    RFID_SPI_DEVICE,
    RFID_SPI_SPEED_HZ,
    SIMULATED_RFID_INTERVAL_SECONDS,
    SIMULATED_RFID_UID,
    TEST_IMAGE_PATH,
)
from detector import YoloObjectDetector
from hardware import HardwareConfig, HardwareController
from matrix import (
    MatrixDisplay,
    build_frame,
    render_ascii,
    render_frames_ascii,
    state_to_frames,
)
from rfid import RFIDHardwareError, build_rfid_reader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kitunga Pi client diagnostics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pir = subparsers.add_parser("pir", help="Read PIR presence")
    pir.add_argument("--duration", type=float, default=5.0)
    pir.add_argument("--interval", type=float, default=0.5)

    buzzer = subparsers.add_parser("buzzer", help="Test buzzer patterns")
    buzzer.add_argument(
        "--pattern",
        choices=["accepted", "payment", "error", "all"],
        default="all",
    )

    matrix = subparsers.add_parser("matrix", help="Test MAX7219 matrix")
    matrix.add_argument("--state", default="WAITING_CUSTOMER")
    matrix.add_argument("--identifier", type=int)
    matrix.add_argument("--hardware", action="store_true")
    matrix.add_argument("--cycle-states", action="store_true")
    matrix.add_argument("--pause", type=float, default=1.5)

    rfid = subparsers.add_parser("rfid", help="Read RFID UID")
    rfid.add_argument("--mode", default=RFID_MODE, choices=["simulation", "hardware"])
    rfid.add_argument(
        "--reads",
        type=int,
        default=None,
        help="number of successful UID reads; default is 3 in simulation and unlimited in hardware",
    )
    rfid.add_argument("--interval", type=float, default=0.5)

    camera = subparsers.add_parser("camera", help="Capture one camera frame")
    camera.add_argument(
        "--camera-backend",
        default=CAMERA_BACKEND,
        choices=["auto", "picamera2", "libcamera", "opencv"],
    )
    camera.add_argument("--camera-index", type=int, default=CAMERA_INDEX)
    camera.add_argument("--width", type=int, default=CAPTURE_WIDTH)
    camera.add_argument("--height", type=int, default=CAPTURE_HEIGHT)
    camera.add_argument("--test-image", default=TEST_IMAGE_PATH)

    yolo = subparsers.add_parser("yolo", help="Run YOLO on one image")
    yolo.add_argument("--model-path", default="")
    yolo.add_argument("--test-image", default=TEST_IMAGE_PATH)

    api = subparsers.add_parser("api", help="Run a minimal API workflow")
    api.add_argument("--api-mode", default=API_MODE, choices=["mock", "real"])
    api.add_argument("--api-base-url", default=API_BASE_URL)
    api.add_argument("--device-id", default=DEVICE_ID)
    api.add_argument("--rfid-uid", default=SIMULATED_RFID_UID)
    api.add_argument("--label", default="ESP32")
    api.add_argument("--confidence", type=float, default=0.95)
    return parser


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    args = build_parser().parse_args()
    return int(getattr(_Commands, args.command)(args) or 0)


class _Commands:
    @staticmethod
    def pir(args: argparse.Namespace) -> int:
        hardware = _hardware(matrix_enabled=False)
        end_at = time.monotonic() + args.duration
        try:
            while time.monotonic() < end_at:
                presence = hardware.presence_detected()
                print(f"presence_detected={presence}")
                time.sleep(args.interval)
        finally:
            hardware.close()
        return 0

    @staticmethod
    def buzzer(args: argparse.Namespace) -> int:
        hardware = _hardware(matrix_enabled=False)
        try:
            print(
                "buzzer_pin={pin} type={type} active_high={active_high} frequency_hz={frequency}".format(
                    pin=BUZZER_PIN,
                    type=BUZZER_TYPE,
                    active_high=BUZZER_ACTIVE_HIGH,
                    frequency=BUZZER_FREQUENCY_HZ,
                )
            )
            patterns = [args.pattern] if args.pattern != "all" else ["accepted", "payment", "error"]
            for pattern in patterns:
                print(f"buzzer:{pattern}")
                if pattern == "accepted":
                    hardware.beep_detection()
                elif pattern == "payment":
                    hardware.beep_payment_success()
                elif pattern == "error":
                    hardware.beep_error()
                time.sleep(0.3)
        finally:
            hardware.close()
        return 0

    @staticmethod
    def matrix(args: argparse.Namespace) -> int:
        states = (
            "WAITING_CUSTOMER",
            "ACTIVE",
            "PRODUCT_ADDED",
            "CHECKOUT_PENDING",
            "PAYMENT_SUCCESS",
            "ERROR",
        )
        if args.cycle_states:
            for state in states:
                print(state)
                print(render_frames_ascii(state_to_frames(state, MATRIX_CASCADED)))
            if not args.hardware:
                return 0

            with MatrixDisplay(
                device=MATRIX_DEVICE,
                intensity=MATRIX_INTENSITY,
                speed_hz=MATRIX_SPEED_HZ,
                cascaded=MATRIX_CASCADED,
                reverse_order=MATRIX_REVERSE_ORDER,
            ) as display:
                for state in states:
                    print(f"displaying={state}", flush=True)
                    display.show_state(state)
                    time.sleep(args.pause)
            return 0

        if args.identifier is not None:
            print(render_ascii(build_frame(args.identifier)))
            if not args.hardware:
                return 0

        print(render_frames_ascii(state_to_frames(args.state, MATRIX_CASCADED)))
        if not args.hardware:
            return 0

        with MatrixDisplay(
            device=MATRIX_DEVICE,
            intensity=MATRIX_INTENSITY,
            speed_hz=MATRIX_SPEED_HZ,
            cascaded=MATRIX_CASCADED,
            reverse_order=MATRIX_REVERSE_ORDER,
        ) as display:
            if args.identifier is not None:
                display.show_identifier(args.identifier)
            else:
                display.show_state(args.state)
            time.sleep(1.5)
        return 0

    @staticmethod
    def rfid(args: argparse.Namespace) -> int:
        target_reads = args.reads
        if target_reads is None:
            target_reads = 0 if args.mode == "hardware" else 3

        try:
            reader = build_rfid_reader(
                mode=args.mode,
                simulated_uid=SIMULATED_RFID_UID,
                simulated_interval_seconds=SIMULATED_RFID_INTERVAL_SECONDS,
                spi_bus=RFID_SPI_BUS,
                spi_device=RFID_SPI_DEVICE,
                rst_pin=RFID_RST_PIN,
                spi_speed_hz=RFID_SPI_SPEED_HZ,
                absent_reads_to_rearm=RFID_ABSENT_READS_TO_REARM,
            )
        except RFIDHardwareError as exc:
            print(f"RFID hardware error: {exc}", file=sys.stderr)
            return 1

        if args.mode == "hardware":
            device_path = f"/dev/spidev{RFID_SPI_BUS}.{RFID_SPI_DEVICE}"
            print("RFID hardware ready")
            print(f"SPI={device_path} RST_GPIO={RFID_RST_PIN}")
            print("Waiting for card...")
        else:
            print("RFID simulation ready")

        successful_reads = 0
        try:
            while target_reads == 0 or successful_reads < target_reads:
                uid = reader.read_uid()
                if uid:
                    print(f"UID={uid}", flush=True)
                    successful_reads += 1
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print()
        finally:
            close = getattr(reader, "close", None)
            if callable(close):
                close()
        return 0

    @staticmethod
    def camera(args: argparse.Namespace) -> int:
        if args.test_image:
            image_path = capture_image(test_image_path=Path(args.test_image))
            frame = cv2.imread(str(image_path))
            if frame is None:
                raise RuntimeError(f"Could not read test image: {image_path}")
            print(f"test_image={image_path} shape={frame.shape}")
            return 0

        camera = CameraManager(
            camera_index=args.camera_index,
            camera_backend=args.camera_backend,
            width=args.width,
            height=args.height,
        )
        try:
            if camera.is_streaming:
                frame = camera.get_frame()
                if frame is None:
                    raise RuntimeError("Camera did not return a frame")
                print(f"camera_backend={camera.backend} shape={frame.shape}")
            else:
                image_path = camera.capture_image()
                print(f"camera_backend={camera.backend} image={image_path}")
        finally:
            camera.release()
        return 0

    @staticmethod
    def yolo(args: argparse.Namespace) -> int:
        if not args.test_image:
            raise RuntimeError("Provide --test-image for YOLO diagnostics.")

        detector = YoloObjectDetector(args.model_path or MODEL_PATH)
        detections = detector.detect(Path(args.test_image))
        print(f"detections={len(detections)}")
        for index, detection in enumerate(detections, start=1):
            print(
                "#{index} label={label} confidence={confidence:.4f} bbox={bbox}".format(
                    index=index,
                    label=detection.label,
                    confidence=detection.confidence,
                    bbox=detection.bbox_xyxy,
                )
            )
        return 0

    @staticmethod
    def api(args: argparse.Namespace) -> int:
        client = build_api_client(
            mode=args.api_mode,
            base_url=args.api_base_url,
            device_id=args.device_id,
            timeout=REQUEST_TIMEOUT,
        )
        started = client.start_session(args.rfid_uid)
        print(f"start_session ok={started.ok} status={started.status} data={started.data} error={started.error}")
        if not started.ok:
            return 1

        added = client.send_detection(args.label, args.confidence)
        print(f"send_detection ok={added.ok} status={added.status} data={added.data} error={added.error}")

        status = client.get_invoice_status()
        print(f"get_invoice_status ok={status.ok} status={status.status} data={status.data} error={status.error}")

        paid = client.confirm_rfid_payment(args.rfid_uid)
        print(f"confirm_rfid_payment ok={paid.ok} status={paid.status} data={paid.data} error={paid.error}")
        return 0 if paid.ok else 1


def _hardware(*, matrix_enabled: bool) -> HardwareController:
    return HardwareController(
        HardwareConfig(
            enabled=HARDWARE_ENABLED,
            pir_pin=PIR_PIN,
            pir_active_high=PIR_ACTIVE_HIGH,
            buzzer_pin=BUZZER_PIN,
            buzzer_active_high=BUZZER_ACTIVE_HIGH,
            buzzer_type=BUZZER_TYPE,
            buzzer_frequency_hz=BUZZER_FREQUENCY_HZ,
            matrix_enabled=MATRIX_ENABLED and matrix_enabled,
            matrix_device=MATRIX_DEVICE,
            matrix_intensity=MATRIX_INTENSITY,
            matrix_speed_hz=MATRIX_SPEED_HZ,
            matrix_cascaded=MATRIX_CASCADED,
            matrix_reverse_order=MATRIX_REVERSE_ORDER,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
