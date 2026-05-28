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
    m = base.Model(modelPath=model_path, deviceID=device_id)
    print(f"[OK] Loaded: {Path(model_path).name}")
    return m


def test_retinaface(model, image_path: str):
    """RetinaFace: BGR, 640x640, mean=[104,117,123] → 期望输出人脸框"""
    from mindx.sdk import Tensor

    img = cv2.imread(image_path)
    assert img is not None, f"Cannot read {image_path}"
    h, w = img.shape[:2]
    print(f"  Input: {w}x{h}")

    t0 = time.perf_counter()
    # 预处理
    inp = cv2.resize(img, (640, 640)).astype(np.float32)
    inp -= (104, 117, 123)
    inp = np.ascontiguousarray(inp.transpose(2, 0, 1)[np.newaxis, ...]).astype(np.float32)
    # 推理
    out = model.infer([Tensor(inp)])[0]
    out.to_host()
    data = np.array(out)
    elapsed = (time.perf_counter() - t0) * 1000

    # 解析输出 (RetinaFace 输出 shape 取决于导出方式)
    print(f"  Output shape: {data.shape}, dtype: {data.dtype}, time: {elapsed:.1f}ms")
    print(f"  Output range: [{data.min():.4f}, {data.max():.4f}]")

    # 尝试统计框数
    det_count = 0
    for row in data.reshape(-1, data.shape[-1]):
        score = float(row[4]) if data.shape[-1] >= 5 else float(row[-1])
        if score > 0.5:
            det_count += 1
    print(f"  Detections (score>0.5): {det_count}")
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

    img = cv2.imread(image_path)
    assert img is not None, f"Cannot read {image_path}"
    h, w = img.shape[:2]

    t0 = time.perf_counter()
    # 预处理
    inp = cv2.dnn.blobFromImage(img, 1 / 255.0, (640, 640), (0, 0, 0), swapRB=True)
    inp = np.ascontiguousarray(inp).astype(np.float32)
    # 推理
    out = model.infer([Tensor(inp)])[0]
    out.to_host()
    data = np.array(out)
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"  Output shape: {data.shape}, dtype: {data.dtype}, time: {elapsed:.1f}ms")
    print(f"  Output range: [{data.min():.4f}, {data.max():.4f}]")

    # 统计 person 检测数
    person_count = 0
    for det in data.reshape(-1, data.shape[-1]):
        if data.shape[-1] >= 6:
            score, cls = float(det[4]), int(det[5])
            if score > 0.4 and cls == 0:
                person_count += 1
    print(f"  Persons detected (score>0.4): {person_count}")
    return person_count > 0


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
