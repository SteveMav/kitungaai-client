from __future__ import annotations

from contextlib import suppress
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from config import CAMERA_BACKEND, CAMERA_INDEX, CAPTURE_HEIGHT, CAPTURE_WIDTH, CAPTURES_DIR

CAMERA_BACKENDS = {"auto", "picamera2", "libcamera", "opencv"}
STREAM_BACKENDS = {"picamera2", "opencv"}
AUTO_BACKEND_ORDER = ("picamera2", "opencv", "libcamera")


def _capture_path(prefix: str = "capture") -> Path:
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return CAPTURES_DIR / f"{prefix}_{timestamp}.jpg"


def capture_image(
    *,
    camera_index: int = CAMERA_INDEX,
    camera_backend: str = CAMERA_BACKEND,
    width: int = CAPTURE_WIDTH,
    height: int = CAPTURE_HEIGHT,
    test_image_path: str | Path | None = None,
) -> Path:
    """Capture an image from a camera, or copy a fixed test image into captures."""
    if test_image_path:
        source = Path(test_image_path)
        if not source.exists():
            raise FileNotFoundError(f"Test image not found: {source}")
        destination = _capture_path("test")
        shutil.copyfile(source, destination)
        return destination

    camera_backend = camera_backend.lower()
    if camera_backend not in CAMERA_BACKENDS:
        raise RuntimeError(f"Unknown camera backend: {camera_backend}. Expected one of {sorted(CAMERA_BACKENDS)}.")

    if camera_backend == "auto":
        errors = []
        for backend in AUTO_BACKEND_ORDER:
            try:
                return _capture_with_backend(backend, camera_index=camera_index, width=width, height=height)
            except Exception as exc:
                errors.append(f"{backend}: {exc}")
        raise RuntimeError("No camera backend worked. " + " | ".join(errors))

    return _capture_with_backend(camera_backend, camera_index=camera_index, width=width, height=height)


class CameraManager:
    """Keep the camera open for live detection, matching the Raspberry Pi hardware client."""

    def __init__(
        self,
        *,
        camera_index: int = CAMERA_INDEX,
        camera_backend: str = CAMERA_BACKEND,
        width: int = CAPTURE_WIDTH,
        height: int = CAPTURE_HEIGHT,
        warmup_seconds: float = 1.5,
    ) -> None:
        camera_backend = camera_backend.lower()
        if camera_backend not in CAMERA_BACKENDS:
            raise RuntimeError(f"Unknown camera backend: {camera_backend}. Expected one of {sorted(CAMERA_BACKENDS)}.")

        self.camera_index = camera_index
        self.requested_backend = camera_backend
        self.width = width
        self.height = height
        self.warmup_seconds = warmup_seconds
        self.backend: str | None = None
        self.cap = None
        self.picam2 = None
        self.libcamera_command: str | None = None

        if camera_backend == "auto":
            self._init_auto()
        else:
            self._init_backend(camera_backend)

    def __enter__(self) -> "CameraManager":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()

    @property
    def is_streaming(self) -> bool:
        return self.backend in STREAM_BACKENDS

    def _init_auto(self) -> None:
        errors = []
        for backend in AUTO_BACKEND_ORDER:
            try:
                self._init_backend(backend)
                return
            except Exception as exc:
                self.release()
                errors.append(f"{backend}: {exc}")
        raise RuntimeError("No camera backend worked. " + " | ".join(errors))

    def _init_backend(self, backend: str) -> None:
        if backend == "picamera2":
            self._init_picamera2()
        elif backend == "opencv":
            self._init_opencv()
        elif backend == "libcamera":
            self._init_libcamera()
        else:
            raise RuntimeError(f"Unsupported backend: {backend}")

    def _init_picamera2(self) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise RuntimeError("picamera2 is not available in this Python environment.") from exc

        camera = Picamera2()
        started = False
        try:
            config = camera.create_preview_configuration(
                main={"size": (self.width, self.height), "format": "BGR888"}
            )
            camera.configure(config)
            camera.start()
            started = True
            time.sleep(min(self.warmup_seconds, 0.5))
            frame = camera.capture_array()
            if frame is None:
                raise RuntimeError("Picamera2 did not return an image.")
        except Exception:
            if started:
                with suppress(Exception):
                    camera.stop()
            with suppress(Exception):
                camera.close()
            raise

        self.picam2 = camera
        self.backend = "picamera2"

    def _init_opencv(self) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("OpenCV is missing. Install dependencies with: pip install -r requirements.txt") from exc

        camera = cv2.VideoCapture(self.camera_index)
        try:
            if not camera.isOpened():
                raise RuntimeError(f"Camera index {self.camera_index} is not available.")
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

            time.sleep(self.warmup_seconds)
            for _attempt in range(5):
                ok, frame = camera.read()
                if ok and frame is not None:
                    self.cap = camera
                    self.backend = "opencv"
                    return
                time.sleep(0.2)
        except Exception:
            camera.release()
            raise

        camera.release()
        raise RuntimeError("Camera did not return an image during warmup.")

    def _init_libcamera(self) -> None:
        command = shutil.which("rpicam-still") or shutil.which("libcamera-still")
        if command is None:
            raise RuntimeError("Neither rpicam-still nor libcamera-still is installed.")

        self.libcamera_command = command
        self.backend = "libcamera"

    def get_frame(self):
        if self.backend == "picamera2" and self.picam2 is not None:
            return self.picam2.capture_array()

        if self.backend == "opencv" and self.cap is not None and self.cap.isOpened():
            ok, frame = self.cap.read()
            if ok:
                return frame

        return None

    def capture_image(self) -> Path:
        if self.backend == "libcamera":
            return _capture_with_libcamera(width=self.width, height=self.height)

        frame = self.get_frame()
        if frame is None:
            raise RuntimeError("Camera did not return an image.")

        return _write_frame(frame, _capture_path(self.backend or "capture"))

    def release(self) -> None:
        if self.picam2 is not None:
            with suppress(Exception):
                self.picam2.stop()
            with suppress(Exception):
                self.picam2.close()
            self.picam2 = None

        if self.cap is not None:
            with suppress(Exception):
                if self.cap.isOpened():
                    self.cap.release()
            self.cap = None

        self.backend = None


def _capture_with_backend(backend: str, *, camera_index: int, width: int, height: int) -> Path:
    if backend == "picamera2":
        return _capture_with_picamera2(width=width, height=height)
    if backend == "libcamera":
        return _capture_with_libcamera(width=width, height=height)
    if backend == "opencv":
        return _capture_with_opencv(camera_index=camera_index, width=width, height=height)
    raise RuntimeError(f"Unsupported backend: {backend}")


def _capture_with_picamera2(*, width: int, height: int) -> Path:
    try:
        from picamera2 import Picamera2
    except ImportError as exc:
        raise RuntimeError("picamera2 is not available in this Python environment.") from exc

    image_path = _capture_path("picamera2")
    camera = Picamera2()
    started = False
    try:
        config = camera.create_still_configuration(main={"size": (width, height)})
        camera.configure(config)
        camera.start()
        started = True
        time.sleep(0.2)
        camera.capture_file(str(image_path))
        return image_path
    finally:
        if started:
            with suppress(Exception):
                camera.stop()
        with suppress(Exception):
            camera.close()


def _capture_with_libcamera(*, width: int, height: int) -> Path:
    command = shutil.which("rpicam-still") or shutil.which("libcamera-still")
    if command is None:
        raise RuntimeError("Neither rpicam-still nor libcamera-still is installed.")

    image_path = _capture_path("libcamera")
    result = subprocess.run(
        [
            command,
            "-n",
            "-t",
            "500",
            "--width",
            str(width),
            "--height",
            str(height),
            "-o",
            str(image_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"{Path(command).name} failed: {detail or f'exit code {result.returncode}'}")
    if not image_path.exists():
        raise RuntimeError(f"{Path(command).name} did not create {image_path}")
    return image_path


def _capture_with_opencv(*, camera_index: int, width: int, height: int) -> Path:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is missing. Install dependencies with: pip install -r requirements.txt") from exc

    camera = cv2.VideoCapture(camera_index)
    try:
        if not camera.isOpened():
            raise RuntimeError(f"Camera index {camera_index} is not available.")
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        ok, frame = camera.read()
        if not ok or frame is None:
            raise RuntimeError("Camera did not return an image.")

        return _write_frame(frame, _capture_path("opencv"))
    finally:
        camera.release()


def _write_frame(frame, image_path: Path) -> Path:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is missing. Install dependencies with: pip install -r requirements.txt") from exc

    if not cv2.imwrite(str(image_path), frame):
        raise RuntimeError(f"Could not write capture to {image_path}")
    return image_path
