#!/usr/bin/env python3
"""模型转换 + 预处理正确性验证。

用法:
    source /usr/local/Ascend/mindx_sdk/set_env.sh
    python test_models.py

检查三个模型是否能正常加载、推理、产出合理输出。
"""

import sys
import time
import json
from pathlib import Path

import numpy as np
import cv2
import yaml


def load_config():
    config_path = Path(__file__).resolve().parent.parent / "config" / "edge_config.yaml"
    return yaml.safe_load(open(config_path))


def init_mindx(mindx_home: str, device_id: int = 0):
    sys.path.insert(0, f"{mindx_home}/python")
    from mindx.sdk import base
    base.mx_init()
    print(f"[OK] MindX SDK initialized, device={device_id}")


def load_model(model_path: str, device_id: int = 0):
    from mindx.sdk import base
    m = base.Model(modelPath=model_path, deviceId=device_id)
    print(f"[OK] Loaded: {Path(model_path).name}")
    return m


def test_retinaface(model, image_path: str):
    """RetinaFace: BGR, 640x640, mean=[104,117,123] → PriorBox decode + NMS"""
    from mindx.sdk import Tensor
    from inference.face_engine import _generate_priors, _nms

    img = cv2.imread(image_path)
    assert img is not None, f"Cannot read {image_path}"
    h, w = img.shape[:2]
    scale_x, scale_y = w / 640.0, h / 640.0
    print(f"  Input: {w}x{h}")

    t0 = time.perf_counter()
    # 预处理
    inp = cv2.resize(img, (640, 640)).astype(np.float32)
    inp -= (104, 117, 123)
    inp = np.ascontiguousarray(inp.transpose(2, 0, 1)[np.newaxis, ...]).astype(np.float32)
    # 推理（三路输出）
    outputs = model.infer([Tensor(inp)])
    for o in outputs:
        o.to_host()

    # 打印所有输出 shape，确定正确的索引映射
    raw_tensors = [np.array(o) for o in outputs]
    for i, t in enumerate(raw_tensors):
        print(f"  output[{i}]: shape={t.shape}")

    # 根据列数确定：4列=bbox, 2列=cls, 10列=landmark
    bbox_idx = cls_idx = None
    for i, t in enumerate(raw_tensors):
        dims = t.shape
        col = dims[-1] if len(dims) >= 2 else None
        if col == 4: bbox_idx = i
        elif col == 2: cls_idx = i

    if bbox_idx is None or cls_idx is None:
        print(f"  Could not identify outputs (bbox_idx={bbox_idx}, cls_idx={cls_idx})")
        return False

    cls_raw = raw_tensors[cls_idx].reshape(16800, 2)
    loc_raw = raw_tensors[bbox_idx].reshape(16800, 4)

    scores_all = cls_raw[:, 1]
    print(f"  cls score range: [{scores_all.min():.6f}, {scores_all.max():.6f}]")
    print(f"  cls score>0.5 count (raw): {(scores_all > 0.5).sum()}")
    print(f"  cls score>0.02 count (raw): {(scores_all > 0.02).sum()}")

    # PriorBox decode
    priors = _generate_priors(640, 640)
    variance = [0.1, 0.2]
    dcx = loc_raw[:, 0] * variance[0] * priors[:, 2] + priors[:, 0]
    dcy = loc_raw[:, 1] * variance[0] * priors[:, 3] + priors[:, 1]
    dw = np.exp(loc_raw[:, 2] * variance[1]) * priors[:, 2]
    dh = np.exp(loc_raw[:, 3] * variance[1]) * priors[:, 3]
    x1 = dcx - dw / 2.0
    y1 = dcy - dh / 2.0
    x2 = dcx + dw / 2.0
    y2 = dcy + dh / 2.0

    scores = cls_raw[:, 1]
    keep = scores > 0.02
    print(f"  After score>0.02: {keep.sum()} candidates")
    x1, y1, x2, y2 = x1[keep], y1[keep], x2[keep], y2[keep]
    scores = scores[keep]

    # 归一化坐标 → 像素坐标 (640)
    x1 *= 640; y1 *= 640; x2 *= 640; y2 *= 640
    x1 = np.clip(x1, 0, 640); y1 = np.clip(y1, 0, 640)
    x2 = np.clip(x2, 0, 640); y2 = np.clip(y2, 0, 640)
    w_box = x2 - x1; h_box = y2 - y1
    keep_idx = (w_box > 5) & (h_box > 5)
    x1, y1, x2, y2 = x1[keep_idx], y1[keep_idx], x2[keep_idx], y2[keep_idx]
    scores = scores[keep_idx]
    print(f"  After size>5x5 filter: {len(scores)} candidates")
    print(f"  Max score before NMS: {scores.max():.6f}")

    # NMS
    indices = _nms(x1, y1, x2, y2, scores, iou_thresh=0.4)
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"  Output shapes: cls={cls_raw.shape}, loc={loc_raw.shape}, time: {elapsed:.1f}ms")
    det_count = sum(1 for i in indices if scores[i] >= 0.5)
    print(f"  Faces detected (score>0.5, after NMS): {det_count}")
    for i in indices:
        if scores[i] >= 0.5:
            print(f"    [{int(x1[i]*scale_x)},{int(y1[i]*scale_y)} {int(x2[i]*scale_x)}x{int(y2[i]*scale_y)}] score={scores[i]:.4f}")
    return det_count > 0


def test_arcface(model, image_path: str):
    """ArcFace: RGB, 112x112, (x/127.5-1.0) → 期望输出 512-dim 特征"""
    from mindx.sdk import Tensor

    img = cv2.imread(image_path)
    assert img is not None, f"Cannot read {image_path}"

    # 模拟人脸 crop (取中心 112x112)
    h, w = img.shape[:2]
    cx, cy = w // 2, h // 2
    crop = img[cy - 56:cy + 56, cx - 56:cx + 56]
    if crop.shape[0] != 112 or crop.shape[1] != 112:
        crop = cv2.resize(img, (112, 112))

    t0 = time.perf_counter()
    # 预处理
    inp = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32)
    inp = (inp / 127.5) - 1.0
    inp = np.ascontiguousarray(inp.transpose(2, 0, 1)[np.newaxis, ...]).astype(np.float32)
    # 推理
    out = model.infer([Tensor(inp)])[0]
    out.to_host()
    feature = np.array(out).flatten()
    elapsed = (time.perf_counter() - t0) * 1000

    # L2 归一化后的余弦相似度自检 (同一张图两次推理应该 ≥ 0.99)
    inp2 = np.ascontiguousarray(
        cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32)
    )
    inp2 = (inp2 / 127.5) - 1.0
    inp2 = np.ascontiguousarray(inp2.transpose(2, 0, 1)[np.newaxis, ...]).astype(np.float32)
    out2 = model.infer([Tensor(inp2)])[0]
    out2.to_host()
    f2 = np.array(out2).flatten()
    f1 = feature / (np.linalg.norm(feature) + 1e-8)
    f2_n = f2 / (np.linalg.norm(f2) + 1e-8)
    self_sim = float(np.dot(f1, f2_n))

    print(f"  Feature dim: {len(feature)}, time: {elapsed:.1f}ms")
    print(f"  Feature range: [{feature.min():.4f}, {feature.max():.4f}]")
    print(f"  Self-similarity (L2): {self_sim:.6f}")
    return len(feature) > 0 and self_sim > 0.95


def test_yolov5m(model, image_path: str):
    """YOLOv5m: RGB, 640x640, /255 → 期望检测到 person (class 0)"""
    from mindx.sdk import Tensor
    from inference.face_engine import _nms

    img = cv2.imread(image_path)
    assert img is not None, f"Cannot read {image_path}"
    h, w = img.shape[:2]
    scale_x, scale_y = w / 640.0, h / 640.0

    t0 = time.perf_counter()
    # 预处理
    inp = cv2.dnn.blobFromImage(img, 1 / 255.0, (640, 640), (0, 0, 0), swapRB=True)
    inp = np.ascontiguousarray(inp).astype(np.float16)
    # 推理
    out = model.infer([Tensor(inp)])[0]
    out.to_host()
    data = np.array(out).reshape(-1, 85)  # (25200, 85)
    elapsed = (time.perf_counter() - t0) * 1000

    # 提取 person (class 0) 检测
    scores = data[:, 4]  # objectness
    person_mask = scores > 0.4

    if person_mask.sum() == 0:
        print(f"  Output shape: (1, 25200, 85), dtype: float16, time: {elapsed:.1f}ms")
        print(f"  Persons detected: 0")
        return False

    pers = data[person_mask]
    scores = pers[:, 4]

    # YOLO bbox 可能是 [x1, y1, x2, y2] 像素坐标 或 [cx, cy, w, h] 归一化
    # 先按像素坐标试：如果值域在 [0, 640] 内则是像素坐标
    raw_max = max(pers[:, 0].max(), pers[:, 1].max(), pers[:, 2].max(), pers[:, 3].max())
    print(f"  Bbox coordinate range (raw): [{0:.1f}, {raw_max:.1f}]")

    if raw_max <= 640:
        # [x1, y1, x2, y2] 已在 640 像素空间
        x1 = np.clip(pers[:, 0], 0, 640); y1 = np.clip(pers[:, 1], 0, 640)
        x2 = np.clip(pers[:, 2], 0, 640); y2 = np.clip(pers[:, 3], 0, 640)
    else:
        # 归一化 [cx, cy, w, h] → 像素 [x1, y1, x2, y2]
        cx, cy = pers[:, 0], pers[:, 1]
        bw, bh = pers[:, 2], pers[:, 3]
        x1 = np.clip((cx - bw / 2.0) * 640, 0, 640)
        y1 = np.clip((cy - bh / 2.0) * 640, 0, 640)
        x2 = np.clip((cx + bw / 2.0) * 640, 0, 640)
        y2 = np.clip((cy + bh / 2.0) * 640, 0, 640)

    indices = _nms(x1, y1, x2, y2, scores, iou_thresh=0.5)

    print(f"  Output shape: (1, 25200, 85), dtype: float16, time: {elapsed:.1f}ms")
    print(f"  Raw person candidates: {person_mask.sum()}, after NMS: {len(indices)}")
    for i in indices:
        print(f"    [{int(x1[i]*scale_x)},{int(y1[i]*scale_y)} {int(x2[i]*scale_x)}x{int(y2[i]*scale_y)}] score={scores[i]:.4f}")

    return len(indices) > 0


def main():
    config = load_config()
    paths = config["paths"]
    inf = config["inference"]

    # Step 1: 初始化 MindX SDK
    init_mindx(paths["mindx_home"], inf.get("device_id", 0))

    # Step 2: 加载三个模型
    models = {}
    for name, key in [
        ("retinaface", "face_detection_model"),
        ("arcface", "face_recognition_model"),
        ("yolov5m", "behavior_model"),
    ]:
        try:
            models[name] = load_model(inf[key], inf.get("device_id", 0))
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            models[name] = None

    # Step 3: 测试图片 (找一张有人脸的图)
    test_img = Path(paths.get("face_lib", "")) / "photos"
    if test_img.exists():
        images = list(test_img.glob("*.jpg")) + list(test_img.glob("*.png"))
    else:
        images = []
    if not images:
        images = list(Path("/data/benchmark_images").glob("*.jpg")) if Path("/data/benchmark_images").exists() else []
    if not images:
        print("[SKIP] No test images found. Place images in face_lib/photos/ or /data/benchmark_images/")
        return

    image_path = str(images[0])
    print(f"\nTest image: {image_path}\n")

    # Step 4: 逐个测试
    results = {}

    if models["retinaface"] is not None:
        print("--- RetinaFace [1,3,640,640] BGR mean-sub ---")
        try:
            ok = test_retinaface(models["retinaface"], image_path)
            status = "PASS" if ok else "WARN (no detections)"
        except Exception as e:
            ok, status = False, f"FAIL: {e}"
        results["retinaface"] = status
        print(f"  Result: {status}\n")

    if models["arcface"] is not None:
        print("--- ArcFace [1,3,112,112] RGB (x/127.5-1) ---")
        try:
            ok = test_arcface(models["arcface"], image_path)
            status = "PASS" if ok else "WARN (self-sim too low)"
        except Exception as e:
            ok, status = False, f"FAIL: {e}"
        results["arcface"] = status
        print(f"  Result: {status}\n")

    if models["yolov5m"] is not None:
        print("--- YOLOv5m [1,3,640,640] RGB /255 ---")
        try:
            ok = test_yolov5m(models["yolov5m"], image_path)
            status = "PASS" if ok else "WARN (no persons)"
        except Exception as e:
            ok, status = False, f"FAIL: {e}"
        results["yolov5m"] = status
        print(f"  Result: {status}\n")

    print("=" * 50)
    print(json.dumps(results, indent=2))
    if all("PASS" in v for v in results.values()):
        print("All models OK.")
    elif all("FAIL" not in v for v in results.values()):
        print("All models loaded, some WARN (check test image content).")
    else:
        print("Some models FAILed — check error messages above.")


if __name__ == "__main__":
    main()
