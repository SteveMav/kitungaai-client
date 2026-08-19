from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config import MODEL_PATH


@dataclass(frozen=True)
class DetectionResult:
    label: str | None
    confidence: float
    bbox_xyxy: tuple[int, int, int, int] | None = None

    @property
    def found(self) -> bool:
        return self.label is not None


class YoloObjectDetector:
    def __init__(self, model_path: str | Path = MODEL_PATH):
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"YOLO model not found: {self.model_path}. Put your trained best.pt file in kitunga_pi_client/models/."
            )

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Ultralytics is missing. Install dependencies with: pip install -r requirements.txt") from exc

        self.model = YOLO(str(self.model_path))

    def detect(self, image_path: str | Path) -> DetectionResult:
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        return self._detect_source(str(image_path))

    def detect_frame(self, frame) -> DetectionResult:
        return self._detect_source(frame)

    def _detect_source(self, source) -> DetectionResult:
        results = self.model(source, verbose=False)
        if not results:
            return DetectionResult(label=None, confidence=0.0)

        result = results[0]
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return DetectionResult(label=None, confidence=0.0)

        confidences = boxes.conf
        best_index = int(confidences.argmax().item())
        confidence = float(confidences[best_index].item())
        class_id = int(boxes.cls[best_index].item())
        label = _label_from_class_id(result.names, class_id)
        bbox = None
        if getattr(boxes, "xyxy", None) is not None:
            coordinates = boxes.xyxy[best_index].tolist()
            bbox = tuple(int(round(value)) for value in coordinates[:4])

        return DetectionResult(label=label, confidence=confidence, bbox_xyxy=bbox)


def _label_from_class_id(names, class_id: int) -> str:
    if isinstance(names, dict):
        return str(names.get(class_id, class_id))
    return str(names[class_id])


_default_detector: YoloObjectDetector | None = None


def detect(image_path: str | Path) -> DetectionResult:
    global _default_detector
    if _default_detector is None:
        _default_detector = YoloObjectDetector()
    return _default_detector.detect(image_path)
