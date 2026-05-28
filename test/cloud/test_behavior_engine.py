import asyncio
import base64

import cv2
import numpy as np
import pytest

from inference.behavior_engine import BehaviorEngine, ImageDecodeError


class FakeDetector:
    def __init__(self, detections):
        self.detections = detections
        self.calls = []

    def detect(self, image):
        self.calls.append(image.shape)
        return self.detections


def run(coro):
    return asyncio.run(coro)


def jpeg_bytes():
    image = np.zeros((80, 120, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def test_behavior_engine_decodes_base64_image_and_returns_behavior_summary():
    detector = FakeDetector([
        {"x1": 10, "y1": 10, "x2": 90, "y2": 70, "score": 0.9, "class_id": 0},
        {"x1": 95, "y1": 20, "x2": 115, "y2": 70, "score": 0.8, "class_id": 0},
    ])
    engine = BehaviorEngine(detector=detector, use_rule_engine=True)
    encoded = base64.b64encode(jpeg_bytes()).decode("ascii")

    result = run(engine.analyze_base64(encoded))

    assert detector.calls
    assert result["total_detected"] == 2
    assert result["hand_up"] == 1
    assert result["standing"] == 0
    assert result["head_down"] == 0
    assert result["talking"] >= 0


def test_behavior_engine_handles_no_person_detected():
    engine = BehaviorEngine(detector=FakeDetector([]), use_rule_engine=True)

    result = run(engine.analyze(jpeg_bytes()))

    assert result == {
        "hand_up": 0,
        "standing": 0,
        "head_down": 0,
        "talking": 0,
        "total_detected": 0,
    }


def test_behavior_engine_reports_invalid_image_as_failed():
    engine = BehaviorEngine(detector=FakeDetector([]), use_rule_engine=True)

    with pytest.raises(ImageDecodeError):
        run(engine.analyze(b"not-an-image"))


def test_behavior_engine_uses_rule_engine_when_enabled():
    detector = FakeDetector([
        {"x1": 10, "y1": 10, "x2": 80, "y2": 75, "score": 0.9, "class_id": 0},
    ])
    engine = BehaviorEngine(detector=detector, use_rule_engine=True)

    result = run(engine.analyze(jpeg_bytes()))

    assert result["hand_up"] == 1
    assert result["total_detected"] == 1
