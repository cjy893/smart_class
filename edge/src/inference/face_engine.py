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

        # RetinaFace 预处理: BGR, resize 640x640, mean=[104,117,123]
        import cv2
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return []
        h, w = img.shape[:2]
        scale_x, scale_y = w / 640.0, h / 640.0
        inp = cv2.resize(img, (640, 640)).astype(np.float32)
        inp -= (104, 117, 123)
        input_blob = np.ascontiguousarray(
            inp.transpose(2, 0, 1)[np.newaxis, ...]
        ).astype(np.float32)

        from mindx.sdk import Tensor
        outputs = model.infer([Tensor(input_blob)])
        for o in outputs:
            o.to_host()

        loc_raw = np.array(outputs[0]).reshape(16800, 4)
        # outputs[1] = landmark (1,16800,10), 暂不用
        cls_raw = np.array(outputs[1]).reshape(16800, 2)

        # --- PriorBox decode ---
        priors = _generate_priors(640, 640)
        variance = [0.1, 0.2]

        prior_cx = priors[:, 0]
        prior_cy = priors[:, 1]
        prior_w = priors[:, 2]
        prior_h = priors[:, 3]

        dcx = loc_raw[:, 0] * variance[0] * prior_w + prior_cx
        dcy = loc_raw[:, 1] * variance[0] * prior_h + prior_cy
        dw = np.exp(loc_raw[:, 2] * variance[1]) * prior_w
        dh = np.exp(loc_raw[:, 3] * variance[1]) * prior_h

        x1 = dcx - dw / 2.0
        y1 = dcy - dh / 2.0
        x2 = dcx + dw / 2.0
        y2 = dcy + dh / 2.0

        scores = cls_raw[:, 1]  # face class score
        keep = scores > 0.02    # 宽松预筛选，NMS 后精筛

        x1, y1, x2, y2 = x1[keep], y1[keep], x2[keep], y2[keep]
        scores = scores[keep]

        # 归一化坐标 → 像素坐标 (640) → 裁剪
        x1 = np.clip(x1 * 640, 0, 640)
        y1 = np.clip(y1 * 640, 0, 640)
        x2 = np.clip(x2 * 640, 0, 640)
        y2 = np.clip(y2 * 640, 0, 640)

        w_box = x2 - x1
        h_box = y2 - y1
        keep_idx = (w_box > 5) & (h_box > 5)
        x1, y1, x2, y2 = x1[keep_idx], y1[keep_idx], x2[keep_idx], y2[keep_idx]
        scores = scores[keep_idx]

        # NMS
        indices = _nms(x1, y1, x2, y2, scores, iou_thresh=0.4)
        x1, y1, x2, y2 = x1[indices], y1[indices], x2[indices], y2[indices]
        scores = scores[indices]

        # 还原到原始图像坐标
        boxes = []
        for i in range(len(scores)):
            if scores[i] < 0.5:
                continue
            boxes.append(FaceBox(
                float(x1[i]) * scale_x,
                float(y1[i]) * scale_y,
                float(x2[i]) * scale_x,
                float(y2[i]) * scale_y,
                float(scores[i]),
            ))

        return boxes

    async def extract_features(self, face_crop: bytes) -> np.ndarray:
        """提取单张人脸的特征向量。"""
        return await asyncio.to_thread(self._sync_extract_features, face_crop)

    def _sync_extract_features(self, face_crop: bytes) -> np.ndarray:
        model = self.service.get_model("face_recognition")
        if model is None:
            logger.error("face_recognition model not loaded")
            return np.zeros(256, dtype=np.float32)

        # ArcFace 预处理: BGR→RGB, resize 112x112, (x/127.5 - 1.0)
        import cv2
        img = cv2.imdecode(np.frombuffer(face_crop, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return np.zeros(512, dtype=np.float32)
        img = cv2.resize(img, (112, 112))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)
        img = (img / 127.5) - 1.0
        input_blob = np.ascontiguousarray(
            img.transpose(2, 0, 1)[np.newaxis, ...]
        ).astype(np.float32)

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


# ---- PriorBox 生成 (RetinaFace MobileNet 0.25, input=640) ----

def _generate_priors(img_w: int, img_h: int) -> "np.ndarray":
    """生成 RetinaFace 的 anchor prior boxes，返回 (N, 4) [cx, cy, w, h]"""
    steps = [8, 16, 32]
    min_sizes = [[16, 32], [64, 128], [256, 512]]

    priors = []
    for step, min_s in zip(steps, min_sizes):
        fm_w = img_w // step
        fm_h = img_h // step
        for y in range(fm_h):
            cy = (y + 0.5) * step / img_w
            for x in range(fm_w):
                cx = (x + 0.5) * step / img_w
                for s in min_s:
                    priors.append([cx, cy, s / img_w, s / img_w])

    return np.array(priors, dtype=np.float32)


# ---- NMS ----

def _nms(x1: "np.ndarray", y1: "np.ndarray", x2: "np.ndarray",
         y2: "np.ndarray", scores: "np.ndarray",
         iou_thresh: float = 0.4) -> "np.ndarray":
    """返回保留的 index 列表"""
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []

    while len(order) > 0:
        i = order[0]
        keep.append(i)
        if len(order) == 1:
            break

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-8)

        remain = np.where(iou <= iou_thresh)[0]
        order = order[remain + 1]

    return np.array(keep, dtype=np.intp)
