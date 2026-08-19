from __future__ import annotations

import argparse
import logging
import time

from camera import CameraManager
from config import (
    CAMERA_BACKEND,
    CAMERA_INDEX,
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    DEVICE_ID,
    PREVIEW_HOST,
    PREVIEW_PORT,
)
from iot_state import LocalDeviceState
from preview import PreviewServer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kitunga technical camera preview")
    parser.add_argument("--host", default=PREVIEW_HOST)
    parser.add_argument("--port", type=int, default=PREVIEW_PORT)
    parser.add_argument(
        "--camera-backend",
        default=CAMERA_BACKEND,
        choices=["auto", "picamera2", "libcamera", "opencv"],
    )
    parser.add_argument("--camera-index", type=int, default=CAMERA_INDEX)
    parser.add_argument("--width", type=int, default=CAPTURE_WIDTH)
    parser.add_argument("--height", type=int, default=CAPTURE_HEIGHT)
    parser.add_argument("--interval", type=float, default=0.05)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("camera_preview_server")
    args = parse_args()

    state = LocalDeviceState(device_id=DEVICE_ID)
    preview = PreviewServer()
    preview.start(host=args.host, port=args.port)
    preview.update(frame=None, detection=None, state=state)

    camera = None
    try:
        camera = CameraManager(
            camera_index=args.camera_index,
            camera_backend=args.camera_backend,
            width=args.width,
            height=args.height,
        )
        logger.info("Camera opened with backend=%s", camera.backend)

        while True:
            frame = camera.get_frame() if camera.is_streaming else None
            if frame is None and not camera.is_streaming:
                image_path = camera.capture_image()
                import cv2

                frame = cv2.imread(str(image_path))
            preview.update(frame=frame, detection=None, state=state)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
    except Exception as exc:
        logger.exception("Preview server failed: %s", exc)
        return 1
    finally:
        if camera is not None:
            camera.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
