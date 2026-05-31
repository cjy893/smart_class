# 工作进度总结

> 最后更新: 2026-05-28

## 1. 总体状态

| 层 | 语言 | 推理框架 | 代码 | 模型 | 测试 |
|---|---|---|---|---|---|
| 端侧 Milk-V | C++ | TDL SDK | 已完成 | YOLOv8n (.cvimodel) | 未测试 |
| 边侧 Atlas | Python 3.9 | MindX SDK mxVision | 已完成 | 3 个 .om | **全部 PASS** |
| 云端 PC | Python | ONNX Runtime | 未开始 | YOLOv5m (.onnx) | - |

## 2. 边侧代码 (edge/)

```
edge/
├── config/
│   ├── edge_config.yaml
│   └── schedule.json
├── data/
│   └── face_lib/
│       ├── students.json
│       ├── photos/
│       └── embeddings/
├── models/
│   ├── retinaface.om   ✓
│   ├── arcface.om      ✓
│   └── yolov5m.om      ✓
├── requirements.txt
└── src/
    ├── main.py                    # 入口，11 步启动编排
    ├── mqtt_client.py             # paho-mqtt async 封装
    ├── policy.py                  # Greedy / LoadBalance / Adaptive
    ├── scheduler.py               # 调度引擎 (硬约束 + 本地执行 + 云端转发)
    ├── task_manager.py            # Task 生命周期 + 超时 + 去重
    ├── session_manager.py         # Session CRUD + 恢复
    ├── schedule_loader.py         # 课表加载 + 定时检查
    ├── face_lib.py                # 人脸库 (扫描/特征提取/hash 变化检测)
    ├── grpc_client.py             # gRPC 客户端 (预留)
    ├── experiment.py              # 实验模式 benchmark
    ├── test_models.py             # 模型正确性验证脚本
    ├── api/
    │   ├── server.py              # FastAPI + CORS
    │   ├── routes.py              # 全部 REST 端点
    │   └── sse.py                 # SSE 实时推送
    ├── db/
    │   ├── connection.py          # SQLite WAL 模式
    │   ├── models.py              # 全部 dataclass + Enum
    │   ├── repository.py          # 6 个 Repository
    │   └── schema.sql             # 6 张表 DDL
    └── inference/
        ├── inference_service.py   # MindX SDK 生命周期管理
        ├── face_engine.py         # RetinaFace + ArcFace + 余弦匹配
        └── behavior_engine.py     # YOLOv5m + 启发式规则
```

## 3. 模型转换结果

| 模型 | 架构 | 输入 | dtype | 后处理 | 测试增量 |
|---|---|---|---|---|---|
| RetinaFace | MobileNet 0.25 | [1,3,640,640] BGR mean-[104,117,123] | FP32 | PriorBox decode + NMS | 164→NMS→1 脸(0.998) |
| ArcFace | MobileFaceNet w600k_mbf | [1,3,112,112] RGB (x/127.5-1) | FP32 | L2 归一化 | 自相似度 1.000 (512维) |
| YOLOv5m | 标准 YOLOv5m | [1,3,640,640] RGB /255 | **FP16** | NMS(IoU=0.5) | 8→NMS→3人 |

**PyTorch → ONNX 导出教训：**
- 不指定 opset_version（触发 onnxscript 降级崩溃）
- 不用 torch.jit.trace（新版导出器拒收 ScriptModule）
- 导出后合并外部数据（PyTorch 2.x 大模型自动拆权重到 .data 文件）
- onnxsim 简化 + 改 opset_import.version 绕过 ATC 版本限制

**ATC 转换教训：**
- soc_version 必须是 `Ascend310P1`（非 310B4）
- 必须显式指定 `--input_shape`（动态维度报错）
- Model API 参数名是 `deviceId` 非 `deviceID`
- FP16 和 FP32 输入不能混用

## 4. 已修复的问题

| 问题 | 状态 |
|---|---|
| TaskManager 图像数据断链（image base64 丢失） | 已修复 — scheduler 维护 `_task_images` dict |
| ONNX opset 20 不被 ATC 支持 | 已修复 — onnxsim 降级到 opset 11 |
| MindX SDK `deviceID` vs `deviceId` | 已修复 |
| YOLOv5m FP32/FP16 数据类型不匹配 | 已修复 — 改为 FP16 |
| RetinaFace 归一化坐标未乘回 640 像素 | 已修复 |
| RetinaFace 后处理缺 PriorBox decode + NMS | 已修复 |
| YOLOv5m 输出 bbox 格式识别错误 (cxcywh vs xyxy) | 已修复 — 自动检测 |
| Python 3.9 类型注解 `X \| None` 不支持 | 已修复 — 改用 Optional[X] |
| HwHiAiUser 权限问题 (chmod/source denied) | 已修复 — 手动 export |
| mindx Python 包在 HwHiAiUser 环境下未安装 | 已修复 — pip install .whl |

## 5. main.py 启动验证

```
Config loaded          ✓
SQLite initialized     ✓
MQTT connected         ✓
3 models preloaded     ✓  (retinaface + arcface + yolov5m)
FaceLib initialized    ✓  (2 students roster, 1 embedding)
Scheduler initialized  ✓  (adaptive policy)
MQTT subscriptions     ✓
Schedule loaded        ✓  (1 entry)
API server             ✓  (0.0.0.0:8000)
gRPC client started    ✓
Graceful shutdown      ✓  (Ctrl+C)
```

**no errors, clean startup.**

## 6. 待完成

### 端侧
- [ ] YOLOv8n 模型重新验证（当前 `inference_engine.cpp` 已实现但未联调）

### 边侧
- [ ] Mosquitto Broker 安装 (`sudo apt install mosquitto`)
- [ ] `students.json` 中缺失的学生照片补齐
- [ ] gRPC proto 定义 + 生成 Python stub
- [ ] 端侧联调 (MQTT topic + 调度指令)
- [ ] 功能测试: 模拟学期 schedule → 上课签到 → 行为分析

### 云端
- [ ] 云端 service 代码（main.py, MQTT, gRPC server）
- [ ] cloud_config.yaml
- [ ] cloud db schema
- [ ] YOLOv5m.onnx 模型（边侧同模型，ONNXRuntime 加载）
- [ ] 报告生成模块
