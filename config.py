import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CAPTURES_DIR = BASE_DIR / "captures"
LOGS_DIR = BASE_DIR / "logs"


def load_local_env(path: Path) -> None:
    """Load simple KEY=value entries without overriding exported variables."""
    if not path.is_file():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue

        name, value = entry.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not name.replace("_", "").isalnum():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


# Local values for this Raspberry. Exported variables still take precedence,
# which keeps service and diagnostic commands compatible.
load_local_env(BASE_DIR / ".env")


def env_value(name: str, default: str, *aliases: str) -> str:
    for key in (name, *aliases):
        value = os.getenv(key)
        if value is not None:
            return value
    return default


def env_bool(name: str, default: bool, *aliases: str) -> bool:
    value = env_value(name, "", *aliases)
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, *aliases: str) -> int:
    return int(env_value(name, str(default), *aliases))


def env_float(name: str, default: float, *aliases: str) -> float:
    return float(env_value(name, str(default), *aliases))


# API
API_MODE = env_value("API_MODE", "mock", "KITUNGA_API_MODE").strip().lower()
DEFAULT_API_BASE_URL = "http://stevemavuela.local:8000"
API_BASE_URL = env_value(
    "API_BASE_URL",
    DEFAULT_API_BASE_URL,
    "KITUNGA_API_BASE_URL",
)
DEVICE_ID = env_value("DEVICE_ID", "KITUNGA-PI-001", "KITUNGA_DEVICE_ID")
REQUEST_TIMEOUT = env_float("REQUEST_TIMEOUT", 5.0, "KITUNGA_API_TIMEOUT_SECONDS")
API_TIMEOUT_SECONDS = REQUEST_TIMEOUT

# Mock API
MOCK_CUSTOMER_NAME = env_value(
    "MOCK_CUSTOMER_NAME",
    "Monsieur X",
    "KITUNGA_MOCK_CUSTOMER_NAME",
)
MOCK_CUSTOMER_ID = env_value(
    "MOCK_CUSTOMER_ID",
    "CUST-0042",
    "KITUNGA_MOCK_CUSTOMER_ID",
)
# RFID
RFID_MODE = env_value("RFID_MODE", "hardware", "KITUNGA_RFID_MODE").strip().lower()
RFID_SPI_BUS = env_int("RFID_SPI_BUS", 0, "KITUNGA_RFID_SPI_BUS")
RFID_SPI_DEVICE = env_int("RFID_SPI_DEVICE", 1, "KITUNGA_RFID_SPI_DEVICE")
RFID_RST_PIN = env_int("RFID_RST_PIN", 25, "KITUNGA_RFID_RST_PIN")
RFID_SPI_SPEED_HZ = env_int("RFID_SPI_SPEED_HZ", 1_000_000, "KITUNGA_RFID_SPI_SPEED_HZ")
RFID_ABSENT_READS_TO_REARM = env_int(
    "RFID_ABSENT_READS_TO_REARM",
    2,
    "KITUNGA_RFID_ABSENT_READS_TO_REARM",
)
SIMULATED_RFID_UID = env_value(
    "SIMULATED_RFID_UID",
    "C3D54714",
    "KITUNGA_SIMULATED_RFID_UID",
)
SIMULATED_RFID_INTERVAL_SECONDS = env_float(
    "SIMULATED_RFID_INTERVAL_SECONDS",
    2.0,
    "KITUNGA_SIMULATED_RFID_INTERVAL_SECONDS",
)

# YOLO and duplicate suppression
CONFIDENCE_THRESHOLD = env_float(
    "CONFIDENCE_THRESHOLD",
    0.20,
    "KITUNGA_CONFIDENCE_THRESHOLD",
)
COOLDOWN_SECONDS = env_float("COOLDOWN_SECONDS", 4.0, "KITUNGA_COOLDOWN_SECONDS")
DETECTION_STABILITY_FRAMES = env_int(
    "DETECTION_STABILITY_FRAMES",
    2,
    "KITUNGA_DETECTION_STABILITY_FRAMES",
)
DETECTION_DISAPPEAR_FRAMES = env_int(
    "DETECTION_DISAPPEAR_FRAMES",
    3,
    "KITUNGA_DETECTION_DISAPPEAR_FRAMES",
)
PRESENCE_GRACE_SECONDS = env_float(
    "PRESENCE_GRACE_SECONDS",
    3.0,
    "KITUNGA_PRESENCE_GRACE_SECONDS",
)
TRACK_IOU_THRESHOLD = env_float(
    "TRACK_IOU_THRESHOLD",
    0.30,
    "KITUNGA_TRACK_IOU_THRESHOLD",
)
SCAN_INTERVAL_SECONDS = env_float(
    "SCAN_INTERVAL_SECONDS",
    0.5,
    "KITUNGA_SCAN_INTERVAL_SECONDS",
)
BASKET_STATUS_POLL_SECONDS = env_float(
    "BASKET_STATUS_POLL_SECONDS",
    1.0,
    "KITUNGA_BASKET_STATUS_POLL_SECONDS",
)

# Camera
CAMERA_INDEX = env_int("CAMERA_INDEX", 0, "KITUNGA_CAMERA_INDEX")
CAMERA_BACKEND = env_value("CAMERA_BACKEND", "auto", "KITUNGA_CAMERA_BACKEND")
CAPTURE_WIDTH = env_int("CAPTURE_WIDTH", 1280, "KITUNGA_CAPTURE_WIDTH")
CAPTURE_HEIGHT = env_int("CAPTURE_HEIGHT", 720, "KITUNGA_CAPTURE_HEIGHT")
MODEL_PATH = Path(env_value("MODEL_PATH", str(BASE_DIR / "models" / "best.pt"), "KITUNGA_MODEL_PATH"))
TEST_IMAGE_PATH = env_value("TEST_IMAGE_PATH", "", "KITUNGA_TEST_IMAGE_PATH")

# Hardware GPIO. Defaults intentionally preserve the existing config.py values.
HARDWARE_ENABLED = env_bool("HARDWARE_ENABLED", True, "KITUNGA_HARDWARE_ENABLED")
PIR_PIN = env_int("PIR_PIN", 17, "KITUNGA_PIR_PIN")
PIR_ACTIVE_HIGH = env_bool("PIR_ACTIVE_HIGH", True, "KITUNGA_PIR_ACTIVE_HIGH")
BUZZER_PIN = env_int("BUZZER_PIN", 18, "KITUNGA_BUZZER_PIN")
BUZZER_ACTIVE_HIGH = env_bool("BUZZER_ACTIVE_HIGH", False, "KITUNGA_BUZZER_ACTIVE_HIGH")
BUZZER_TYPE = env_value("BUZZER_TYPE", "passive", "KITUNGA_BUZZER_TYPE").strip().lower()
BUZZER_FREQUENCY_HZ = env_int("BUZZER_FREQUENCY_HZ", 2_000, "KITUNGA_BUZZER_FREQUENCY_HZ")

# MAX7219 matrix
MATRIX_ENABLED = env_bool("MATRIX_ENABLED", True, "KITUNGA_MATRIX_ENABLED")
MATRIX_DEVICE = env_value("MATRIX_DEVICE", "/dev/spidev0.0", "KITUNGA_MATRIX_DEVICE")
MATRIX_SPEED_HZ = env_int("MATRIX_SPEED_HZ", 1_000_000, "KITUNGA_MATRIX_SPEED_HZ")
MATRIX_INTENSITY = env_int("MATRIX_INTENSITY", 2, "KITUNGA_MATRIX_INTENSITY")
MATRIX_CASCADED = env_int("MATRIX_CASCADED", 1, "KITUNGA_MATRIX_CASCADED")
MATRIX_REVERSE_ORDER = env_bool(
    "MATRIX_REVERSE_ORDER",
    False,
    "KITUNGA_MATRIX_REVERSE_ORDER",
)
MATRIX_BLOCK_ORIENTATION = env_int(
    "MATRIX_BLOCK_ORIENTATION",
    -90,
    "KITUNGA_MATRIX_BLOCK_ORIENTATION",
)
MATRIX_ROTATE = env_int("MATRIX_ROTATE", 0, "KITUNGA_MATRIX_ROTATE")
MATRIX_CONTRAST = env_int("MATRIX_CONTRAST", 32, "KITUNGA_MATRIX_CONTRAST")
MATRIX_SCROLL_DELAY = env_float(
    "MATRIX_SCROLL_DELAY",
    0.08,
    "KITUNGA_MATRIX_SCROLL_DELAY",
)

# Preview and logs
PREVIEW_ENABLED = env_bool("PREVIEW_ENABLED", True, "KITUNGA_PREVIEW_ENABLED")
PREVIEW_HOST = env_value("PREVIEW_HOST", "0.0.0.0", "KITUNGA_PREVIEW_HOST")
PREVIEW_PORT = env_int("PREVIEW_PORT", 5000, "KITUNGA_PREVIEW_PORT")
LOG_LEVEL = env_value("LOG_LEVEL", "INFO", "KITUNGA_LOG_LEVEL")
LOG_FILE = Path(env_value("LOG_FILE", str(LOGS_DIR / "kitunga_pi_client.log"), "KITUNGA_LOG_FILE"))
