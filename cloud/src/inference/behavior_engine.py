import asyncio
import base64
from typing import Any

import cv2
import numpy as np


class ImageDecodeError(ValueError):
    pass


class OpenCvDnnDetector:
    def __init__(self, model_path: str, confidence_threshold: float = 0.4):
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self._net = None

    def _load_net(self):
        if self._net is None:
            self._net = cv2.dnn.readNetFromONNX(self.model_path)
        return self._net

    def detect(self, image: np.ndarray) -> list[dict[str, float]]:
        net = self._load_net()
        height, width = image.shape[:2]
        blob = cv2.dnn.blobFromImage(
            image, 1 / 255.0, (640, 640), (0, 0, 0), swapRB=True, crop=False
        )
        net.setInput(blob)
        output = net.forward()
        detections = np.asarray(output)
        if detections.ndim == 2:
            detections = detections.reshape(1, *detections.shape)

        persons: list[dict[str, float]] = []
        for det in detections[0]:
            if len(det) < 6:
                continue
            score = float(det[4])
            class_id = int(det[5])
            if score < self.confidence_threshold or class_id != 0:
                continue
            x1 = max(0.0, float(det[0]) * width / 640.0)
            y1 = max(0.0, float(det[1]) * height / 640.0)
            x2 = min(float(width), float(det[2]) * width / 640.0)
            y2 = min(float(height), float(det[3]) * height / 640.0)
            persons.append({
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "score": score,
                "class_id": class_id,
            })
        return persons


class BehaviorEngine:
    def __init__(self, detector=None, use_rule_engine: bool = True):
        self.detector = detector
        self.use_rule_engine = use_rule_engine

    @classmethod
    def from_model_path(cls, model_path: str, use_rule_engine: bool = True):
        return cls(OpenCvDnnDetector(model_path), use_rule_engine=use_rule_engine)

    async def analyze_base64(self, image_base64: str, params: dict[str, Any] | None = None) -> dict[str, int]:
        image_bytes = base64.b64decode(image_base64.encode("ascii"), validate=True)
        return await self.analyze(image_bytes, params)

    async def analyze(self, image_bytes: bytes, params: dict[str, Any] | None = None) -> dict[str, int]:
        return await asyncio.to_thread(self._sync_analyze, image_bytes)

    def _sync_analyze(self, image_bytes: bytes) -> dict[str, int]:
        image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ImageDecodeError("invalid image bytes")

        detections = self.detector.detect(image) if self.detector else []
        persons = [
            d for d in detections
            if int(d.get("class_id", 0)) == 0 and float(d.get("score", 1.0)) >= 0.4
        ]

        if not self.use_rule_engine:
            return _empty_result(total_detected=len(persons))
        return _classify_with_rules(persons, image.shape[0])


def _empty_result(total_detected: int = 0) -> dict[str, int]:
    return {
        "hand_up": 0,
        "standing": 0,
        "head_down": 0,
        "talking": 0,
        "total_detected": total_detected,
    }


def _classify_with_rules(persons: list[dict[str, float]], image_height: int) -> dict[str, int]:
    result = _empty_result(total_detected=len(persons))
    if not persons:
        return result

    heights = [_height(p) for p in persons]
    avg_height = sum(heights) / len(heights)

    for person in persons:
        height = _height(person)
        width = _width(person)
        center_y = (person["y1"] + person["y2"]) / 2.0

        if avg_height > 0 and height < avg_height * 0.7:
            result["head_down"] += 1
            continue
        if avg_height > 0 and (height > avg_height * 1.35 or center_y < image_height * 0.3):
            result["standing"] += 1
            continue
        if height > 0 and width / height > 0.8:
            result["hand_up"] += 1

    result["talking"] = _count_talking(persons)
    return result


def _count_talking(persons: list[dict[str, float]]) -> int:
    talking = 0
    for index, p1 in enumerate(persons):
        for p2 in persons[index + 1:]:
            cx1, cy1 = _center(p1)
            cx2, cy2 = _center(p2)
            distance = ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5
            avg_width = (_width(p1) + _width(p2)) / 2.0
            if avg_width > 0 and distance < avg_width * 2.5:
                talking += 1
    return min(talking, len(persons))


def _height(person: dict[str, float]) -> float:
    return float(person["y2"]) - float(person["y1"])


def _width(person: dict[str, float]) -> float:
    return float(person["x2"]) - float(person["x1"])


def _center(person: dict[str, float]) -> tuple[float, float]:
    return (
        (float(person["x1"]) + float(person["x2"])) / 2.0,
        (float(person["y1"]) + float(person["y2"])) / 2.0,
    )
