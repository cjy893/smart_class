import asyncio
import logging
from typing import Optional

import numpy as np

from inference.inference_service import InferenceService

logger = logging.getLogger(__name__)


class BehaviorResult:
    def __init__(self, hand_up: int = 0, standing: int = 0,
                 head_down: int = 0, talking: int = 0,
                 total_detected: int = 0):
        self.hand_up = hand_up
        self.standing = standing
        self.head_down = head_down
        self.talking = talking
        self.total_detected = total_detected

    def to_dict(self) -> dict:
        return {
            "hand_up": self.hand_up,
            "standing": self.standing,
            "head_down": self.head_down,
            "talking": self.talking,
            "total_detected": self.total_detected,
        }


class BehaviorEngine:
    """人体检测 + 启发式规则行为分类。

    通过 MindX SDK 调用 YOLOv5m.om 做人体检测，
    然后用几何启发式规则判断行为类型（举手/起立/低头/交谈）。
    """

    def __init__(self, service: InferenceService):
        self.service = service

    async def analyze(self, image_bytes: bytes) -> BehaviorResult:
        return await asyncio.to_thread(self._sync_analyze, image_bytes)

    def _sync_analyze(self, image_bytes: bytes) -> BehaviorResult:
        model = self.service.get_model("behavior")
        if model is None:
            logger.error("behavior model not loaded")
            return BehaviorResult()

        import cv2
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return BehaviorResult()
        h, w = img.shape[:2]

        # 预处理
        input_blob = cv2.dnn.blobFromImage(img, 1/255.0, (640, 640), (0, 0, 0), swapRB=True)
        input_blob = np.ascontiguousarray(input_blob).astype(np.float32)

        from mindx.sdk import Tensor
        input_tensor = Tensor(input_blob)
        output = model.infer([input_tensor])[0]
        output.to_host()
        detections = np.array(output)

        # YOLO 输出格式: [batch, num_detections, (x1,y1,x2,y2,conf,cls)]
        persons = []
        for det in detections[0]:
            score = float(det[4])
            cls = int(det[5])
            if score < 0.4 or cls != 0:  # COCO class 0 = person
                continue
            x1 = max(0, float(det[0]) * w / 640.0)
            y1 = max(0, float(det[1]) * h / 640.0)
            x2 = min(w, float(det[2]) * w / 640.0)
            y2 = min(h, float(det[3]) * h / 640.0)
            persons.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})

        result = BehaviorResult(total_detected=len(persons))
        avg_height = np.mean([p["y2"] - p["y1"] for p in persons]) if persons else 0

        for p in persons:
            bh = p["y2"] - p["y1"]
            bw = p["x2"] - p["x1"]
            cy = (p["y1"] + p["y2"]) / 2.0  # bbox 中心 y

            # 低头: 身高显著低于平均值（坐姿，头部位置低）
            if avg_height > 0 and bh < avg_height * 0.7:
                result.head_down += 1
                continue

            # 起立: bbox 高度显著大于平均值，或者中心 y 明显偏上（更高位置）
            if avg_height > 0 and (bh > avg_height * 1.35 or cy < h * 0.3):
                result.standing += 1
                continue

            # 举手: bbox 宽高比异常（手臂抬高增大了宽度）
            if bh > 0 and bw / bh > 0.8:
                result.hand_up += 1
                continue

            # 交谈: 两两 bbox 水平距离很近 < 平均宽度的 1.5 倍
            # 简化处理：在遍历中无法做两两比较，默认归为交谈（最后 fallback）
            # 实际规则引擎应在此做两两距离判断，此处保持简单。
            result.talking += 1

        # 重新计算交谈：检查相邻 bbox
        result.talking = 0
        for i, p1 in enumerate(persons):
            for j, p2 in enumerate(persons):
                if i >= j:
                    continue
                cx1 = (p1["x1"] + p1["x2"]) / 2.0
                cx2 = (p2["x1"] + p2["x2"]) / 2.0
                cy1 = (p1["y1"] + p1["y2"]) / 2.0
                cy2 = (p2["y1"] + p2["y2"]) / 2.0
                dist = ((cx1 - cx2)**2 + (cy1 - cy2)**2)**0.5
                avg_w = ((p1["x2"]-p1["x1"]) + (p2["x2"]-p2["x1"])) / 2.0
                if dist < avg_w * 2.5:
                    result.talking += 1

        result.talking = min(result.talking, len(persons))
        return result
