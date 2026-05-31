# Atlas 200I DK A2 开发指南

## 1. 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Ubuntu 22.04 (开发板预装) |
| Python | **3.9** (MindX SDK 硬性要求，不兼容 3.10+) |
| CANN | Ascend-cann-toolkit (配套 MindX SDK 版本) |
| MindX SDK | mxVision (安装在 `/usr/local/Ascend/mxVision`) |
| 用户 | HwHiAiUser (sudo 受限，需手动处理权限) |

### 1.1 CANN + MindX SDK 安装顺序

```
CANN toolkit → MindX SDK .run 安装包 → pip install mxVision/python/*.whl
```

### 1.2 环境变量

每次使用前必须设置（或写入 `~/.bashrc`）：

```bash
# MindX SDK 库路径
export LD_LIBRARY_PATH=/usr/local/Ascend/mxVision/lib:$LD_LIBRARY_PATH

# Python 包路径（如果 .whl 安装后仍找不到）
export PYTHONPATH=/usr/local/Ascend/mxVision/python:$PYTHONPATH

# 验证
python -c "from mindx.sdk import base; print('OK')"
```

### 1.3 Python 依赖

```bash
pip install numpy opencv-python paho-mqtt fastapi uvicorn pyyaml grpcio
```

## 2. 模型转换流程

### 2.1 完整链路

```
PyTorch .pth → ONNX → (onnxsim 简化) → ATC → .om
```

### 2.2 PyTorch → ONNX

**关键注意事项：**

1. **不要指定 `opset_version`**。PyTorch 2.x 的 onnxscript 导出器不支持低版本 opset。不传参数让它原生导出（opset 18+），后续用 onnxsim 处理。

2. **不要用 `torch.jit.trace`**。ScriptModule 会被新版导出器拒绝。

3. **导出后合并外部数据**（PyTorch 2.x 对大模型自动拆权重到 .data 文件，ATC 不认）：

```python
import onnx

torch.onnx.export(model, dummy_input, "model.onnx",
                   input_names=["input0"],
                   output_names=["output0"])

# 合并外部数据到单文件
m = onnx.load("model.onnx")
onnx.save(m, "model.onnx", save_as_external_data=False)
```

4. **如果 ATC 报 opset 版本不兼容**，用 onnxsim 简化 + 改版本声明：

```bash
pip install onnxsim
python -c "
import onnx
from onnxsim import simplify
m = onnx.load('model.onnx')
m_simp, _ = simplify(m)
m_simp.opset_import[0].version = 11
onnx.save(m_simp, 'model.onnx', save_as_external_data=False)
"
```

### 2.3 ONNX → .om (ATC)

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh

# 通用模板
atc --model=model.onnx --framework=5 --output=model \
    --soc_version=Ascend310P1 \
    --input_format=NCHW \
    --input_shape="input_name:batch,channel,height,width"
```

**常见报错：**

| 错误 | 原因 | 解决 |
|---|---|---|
| `ai.onnx::20::Conv` | opset 太高 | onnxsim 降级 |
| `Value [-1] for parameter [input.X]` | 动态维度未指定 | 加 `--input_shape` |
| `Failed to get real path of ... .data` | 外部权重文件 | 合并到单文件 |
| `Please check inputTensors datasize` | FP32/FP16 不匹配 | 改 `astype()` |
| `E10042: GenerateOfflineModel` | 图解析失败 | onnxsim 简化 |

### 2.4 三个模型的 ATC 参数

| 模型 | input_shape | 备注 |
|---|---|---|
| retinaface | `input0:1,3,640,640` | MobileNet 0.25 |
| arcface | `data:1,3,112,112` | MobileFaceNet w600k_mbf |
| yolov5m | `images:1,3,640,640` | 标准 YOLOv5m |

## 3. 模型预处理规范

> 以下规范假设 ATC 转换时**未使用 `--insert_op_conf` 做 AIPP 预处理**。
> 如果用 AIPP 配置了归一化参数，预处理可以简化。

### 3.1 RetinaFace — 人脸检测

```
输入: BGR, resize 640×640, mean subtraction [104, 117, 123]
  无 scale（不要 /255）

处理:
  img = cv2.resize(img, (640, 640)).astype(np.float32)
  img -= (104, 117, 123)
  img = img.transpose(2, 0, 1)[np.newaxis, ...]  # HWC→CHW, add batch
  dtype: float32

后处理: PriorBox decode + NMS (IoU=0.4)
  输出三路 tensor:
    outputs[0] = bbox deltas  (1, 16800, 4)
    outputs[1] = cls scores   (1, 16800, 2)
    outputs[2] = landmarks    (1, 16800, 10)
```

### 3.2 ArcFace (MobileFaceNet) — 特征提取

```
输入: BGR→RGB, resize 112×112, (x/127.5 - 1.0)

处理:
  img = cv2.resize(img, (112, 112))
  img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)
  img = (img / 127.5) - 1.0
  img = img.transpose(2, 0, 1)[np.newaxis, ...]
  dtype: float32

输出: 512-dim 特征向量 (L2 归一化后使用)
```

### 3.3 YOLOv5m — 人体检测

```
输入: BGR→RGB, resize 640×640, /255

处理:
  cv2.dnn.blobFromImage(img, 1/255.0, (640, 640), (0, 0, 0), swapRB=True)
  dtype: float16 (注意不是 float32！)

输出: (1, 25200, 85)
  bbox 格式: [x1, y1, x2, y2] 像素坐标 (已验证 0~636 范围)
  非 [cx, cy, w, h] 归一化

后处理: NMS (IoU=0.5)
```

## 4. Python 注意事项

### 4.1 Python 3.9 兼容性

开发板 Python 是 3.9，不支持以下 3.10+ 语法：

```python
# 错误: Python 3.9 不支持
def foo(x: dict[str, int] | None = None): ...

# 正确: 用 Optional
from typing import Optional
def foo(x: Optional[dict[str, int]] = None): ...
```

### 4.2 权限问题

HwHiAiUser 没有 sudo 权限。遇到 `Permission denied` 时：

```bash
# chmod 不能 sudo
→ 直接 export LD_LIBRARY_PATH 绕过，不需要 chmod

# 需要 root 的操作
→ 切到 root 用户: su root
```

### 4.3 set_env.sh 权限

如果 `/usr/local/Ascend/mxVision/set_env.sh` 没有读权限且不能 chmod：

```bash
# 不 source，直接手动设环境变量
export LD_LIBRARY_PATH=/usr/local/Ascend/mxVision/lib:$LD_LIBRARY_PATH
```

## 5. 测试方法

### 5.1 模型正确性验证

```bash
cd /home/HwHiAiUser/edge_compute/edge/src
python test_models.py
```

验证项：
- 模型加载成功
- 预处理 → 推理 → 后处理全链路
- ArcFace 自相似度 ≥ 0.99（同一 crop 两次推理的余弦相似度，是确定性的硬指标）
- 输出 shape 和值域符合预期

### 5.2 全服务启动

```bash
python main.py
```

健康检查：
```bash
curl http://localhost:8000/api/v1/nodes/status
curl http://localhost:8000/api/v1/sessions
```

## 6. 常见问题速查

| 问题 | 原因 | 解决 |
|---|---|---|
| `libglog.so.1: cannot open` | LD_LIBRARY_PATH 未设 | export 或 source set_env.sh |
| `No module named 'mindx'` | .whl 未安装 | pip install mxVision/python/*.whl |
| `ModuleNotFoundError: paho` | 缺依赖 | pip install paho-mqtt |
| `TypeError: unsupported operand type for \|` | Python 3.9 不支持 X\|None | 改用 Optional[X] |
| `deviceID` 参数报错 | API 参数名是 `deviceId` | 注意驼峰大小写 |
| 输入 tensor size 不匹配 (2x) | dtype FP32/FP16 不一致 | 检查模型的输入精度 |
| ONNX 导出 opset 版本降级失败 | PyTorch 2.x onnxscript 不支持低 opset | 用 onnxsim 降级 |
| 权限 Permission denied | HwHiAiUser 无 sudo | 手动 export 环境变量 |

## 7. 开发板 vs 本地开发环境差异

| | 本地 (WSL/PC) | Atlas 开发板 |
|---|---|---|
| Python 版本 | 3.11+ | **3.9** |
| PyTorch | GPU 版 | **不安装**（只用 ONNX + ATC） |
| ONNX 导出 | 在本地做 | 只做 ATC 转换 |
| 推理 | 不可用 | MindX SDK |
| 用户权限 | 完整 | HwHiAiUser 受限 |
| 路径 | `/mnt/e/...` | `/home/HwHiAiUser/edge_compute/...` |
