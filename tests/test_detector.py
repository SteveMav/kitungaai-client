from __future__ import annotations

import unittest

from detector import YoloObjectDetector


class _Value:
    def __init__(self, value) -> None:
        self.value = value

    def item(self):
        return self.value


class _Vector:
    def __init__(self, values) -> None:
        self.values = values

    def __getitem__(self, index):
        return _Value(self.values[index])


class _Coordinates:
    def __init__(self, values) -> None:
        self.values = values

    def __getitem__(self, index):
        return _CoordinateRow(self.values[index])


class _CoordinateRow:
    def __init__(self, values) -> None:
        self.values = values

    def tolist(self):
        return self.values


class _Boxes:
    conf = _Vector([0.81, 0.94, 0.76])
    cls = _Vector([0, 1, 0])
    xyxy = _Coordinates(
        [
            [10.0, 20.0, 90.0, 120.0],
            [130.0, 20.0, 230.0, 120.0],
            [260.0, 20.0, 360.0, 120.0],
        ]
    )

    def __len__(self) -> int:
        return 3


class _Result:
    boxes = _Boxes()
    names = {0: "ESP32", 1: "Arduino"}


class _Model:
    def __call__(self, _source, verbose: bool):
        self.verbose = verbose
        return [_Result()]


class YoloObjectDetectorTest(unittest.TestCase):
    def test_keeps_every_yolo_box_instead_of_only_the_highest_confidence_box(self) -> None:
        detector = object.__new__(YoloObjectDetector)
        detector.model = _Model()

        detections = detector.detect_frame(object())

        self.assertEqual([detection.label for detection in detections], ["ESP32", "Arduino", "ESP32"])
        self.assertEqual([detection.confidence for detection in detections], [0.81, 0.94, 0.76])
        self.assertEqual(detections[2].bbox_xyxy, (260, 20, 360, 120))
        self.assertFalse(detector.model.verbose)


if __name__ == "__main__":
    unittest.main()
