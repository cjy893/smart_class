import asyncio
import logging
from typing import Optional

import numpy as np

from inference.inference_service import InferenceService

logger = logging.getLogger(__name__)


class FaceBox:
    def __init__(self, x1: float, y1: float, x2: float, y2: float, score: float):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.score = score


class FaceResult:
    def __init__(self, present: list[dict], absent: list[dict],
                 unknown: int, total_expected: int, attempt: int):
        self.present = present
        self.absent = absent
        self.unknown = unknown
        self.total_expected = total_expected
        self.attempt = attempt


class FaceEngine:
    """人脸检测 + 特征提取 + 身份匹配。

    调用 MindX SDK 加载的 RetinaFace.om (检测) 和 ArcFace.om (特征提取)。
    与人脸库 FaceLib 配合完成 1:N 身份匹配。
    """

    def __init__(self, service: InferenceService):
        self.service = service

    async def detect(self, image_bytes: bytes) -> list[FaceBox]:
        """检测图像中的所有人脸，返回 FaceBox 列表。"""
        return await asyncio.to_thread(self._sync_detect, image_bytes)

    def _sync_detect(self, image_bytes: bytes) -> list[FaceBox]:
        model = self.service.get_model("face_detection")
        if model is None:
            logger.error("face_detection model not loaded")
            return []

        # 预处理: 解码 JPEG → resize → normalize → Tensor
        import cv2
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return []
        h, w = img.shape[:2]
        input_blob = cv2.dnn.blobFromImage(img, 1/255.0, (640, 640), (0, 0, 0), swapRB=True)
        input_blob = np.ascontiguousarray(input_blob).astype(np.float32)

        from mindx.sdk import Tensor
        input_tensor = Tensor(input_blob)
        output = model.infer([input_tensor])[0]
        output.to_host()
        detections = np.array(output)

        boxes = []
        for det in detections[0]:
            score = float(det[4])
            if score < 0.5:
                continue
            x1 = float(det[0]) * w / 640.0
            y1 = float(det[1]) * h / 640.0
            x2 = float(det[2]) * w / 640.0
            y2 = float(det[3]) * h / 640.0
            boxes.append(FaceBox(max(x1,0), max(y1,0), min(x2,w), min(y2,h), score))

        return boxes

    async def extract_features(self, face_crop: bytes) -> np.ndarray:
        """提取单张人脸的特征向量。"""
        return await asyncio.to_thread(self._sync_extract_features, face_crop)

    def _sync_extract_features(self, face_crop: bytes) -> np.ndarray:
        model = self.service.get_model("face_recognition")
        if model is None:
            logger.error("face_recognition model not loaded")
            return np.zeros(256, dtype=np.float32)

        import cv2
        img = cv2.imdecode(np.frombuffer(face_crop, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return np.zeros(256, dtype=np.float32)
        img = cv2.resize(img, (112, 112))
        input_blob = np.ascontiguousarray(
            img.transpose(2, 0, 1).astype(np.float32) / 255.0
        )[np.newaxis, ...]  # (1, 3, 112, 112)

        from mindx.sdk import Tensor
        input_tensor = Tensor(input_blob)
        output = model.infer([input_tensor])[0]
        output.to_host()
        feature = np.array(output).flatten()
        # L2 归一化
        norm = np.linalg.norm(feature)
        if norm > 0:
            feature = feature / norm
        return feature

    async def recognize(self, image_bytes: bytes,
                        face_lib: "FaceLib") -> FaceResult:
        """完整流程：检测 → 特征提取 → 1:N 匹配人脸库。

        face_lib 的 embeddings dict 在启动时预先加载到内存。
        """
        return await asyncio.to_thread(self._sync_recognize, image_bytes, face_lib)

    def _sync_recognize(self, image_bytes: bytes, face_lib: "FaceLib") -> FaceResult:
        boxes = self._sync_detect(image_bytes)
        present_ids: set[str] = set()
        unknown_count = 0

        for box in boxes:
            # 对每个检测到的人脸提取特征并匹配
            import cv2
            img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            h, w = img.shape[:2]
            x1, y1 = max(0, int(box.x1)), max(0, int(box.y1))
            x2, y2 = min(w, int(box.x2)), min(h, int(box.y2))
            if x2 <= x1 or y2 <= y1:
                continue

            crop = img[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            success, buf = cv2.imencode(".jpg", crop)
            if not success:
                continue

            feature = self._sync_extract_features(buf.tobytes())

            # 余弦相似度匹配
            best_id = None
            best_sim = -1
            for sid, emb in face_lib.embeddings.items():
                sim = np.dot(feature, emb)  # 已 L2 归一化，点积即余弦相似度
                if sim > best_sim:
                    best_sim = sim
                    best_id = sid

            if best_id and best_sim >= 0.5:
                present_ids.add(best_id)
            else:
                unknown_count += 1

        present = [
            {"student_id": s.student_id, "name": s.name}
            for s in face_lib.students if s.student_id in present_ids
        ]
        absent = [
            {"student_id": s.student_id, "name": s.name}
            for s in face_lib.students if s.student_id not in present_ids
        ]

        return FaceResult(
            present=present,
            absent=absent,
            unknown=unknown_count,
            total_expected=len(face_lib.students),
            attempt=0,
        )
