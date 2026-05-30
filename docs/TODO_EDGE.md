# 边侧代码待完成项

> 基于 2026-05-29 审计，逐条核实代码后重新排定优先级。
> 更新时间: 2026-05-30 — 4/4 项全部完成，已清零。

## 已确认可工作

- MindX SDK 初始化 + 3 个 .om 模型预加载
- RetinaFace 人脸检测 (PriorBox decode + NMS)
- ArcFace 特征提取 (512-dim, 自相似度 1.000)
- YOLOv5m 人体检测 (NMS)
- FaceLib 人脸库 (扫描/特征提取/.npy 缓存/hash 变化检测)
- MQTT 连接 + topic 订阅
- 端侧 MQTT 连通验证通过 (online 消息正确抵达边侧 on_device_online 回调)
- SQLite 6 表建库 + WAL 模式
- 调度策略 (GreedyNearby / LoadBalance / Adaptive)
- TaskManager 幂等去重 + 超时监控
- FastAPI + SSE 全部端点
- main.py 启动 clean startup 验证通过

---

## 已修复（全部完成）

### P0-1. person_count 数据流断链 ✓

**文件**: `scheduler.py`, `main.py`

- `HARD_CONSTRAINT_DEVICE` 删除，person_count 不再进入调度引擎
- `on_task_request` 过滤 person_count，走独立 `on_person_count` 回调直接入库

### P0-2. 调度队列串行化 ✓

**文件**: `scheduler.py`, `main.py`

- `dispatch()` edge 分支只做 `enqueue_local`，不调用 `_execute_local`
- `periodic_checks` 改为 `asyncio.create_task(scheduler._execute_local(task))` 异步消费

### P0-3. 课表下课回调 ✓

**文件**: `main.py`

- `on_class_end` → `session_mgr.end_session()` → 自动创建 `report_generate` task

### P1-5. behavior_analyze 硬约束重构 ✓

**文件**: `scheduler.py`

- 四种 task_type 各自独立分支（EDGE / CLOUD / POLICY）

### 端侧 MQTT Packet ID 修复 ✓

**文件**: `tdl_sdk/sample/edge_compute_device/mqtt_client.cpp`

- QoS > 0 的 PUBLISH 报文添加 2-byte Packet Identifier

### P1-1. LWT device_offline 订阅 ✓

**文件**: `main.py:206-211`

- 新增 `on_device_offline` 回调 + `subscribe("edge/device/offline/#")`
- 端侧异常断线时边侧可感知

### P2-2. report_generate 聚合数据接入 ✓

**文件**: `scheduler.py:103-117`

- `dispatch()` cloud 分支改为 `payload = await self._build_cloud_request(task)`
- 聚合 `person_count` + `attendance` + `behavior` 数据随请求发往云端

### P2-3. gRPC 客户端实现 ✓

**文件**: `grpc_client.py`, `proto/edge_report_pb2_grpc.py`

- Proto 定义: `cloud/proto/edge_report.proto` (ReportStatus + Heartbeat + Ack)
- Stub 复制到 `edge/src/proto/`，补齐客户端 `EdgeReportStub` 类
- `GrpcClient._report()` 每 30s 发送 StatusReport (CPU/NPU/Memory/设备数) + Heartbeat
- `requirements.txt` 新增 `grpcio>=1.50`

---

## 待完成项

**无。** 所有待办已清零。

P2-4 (Experiment 接入) 经确认属于非核心基准测试工具，不影响线上业务流程，标记为暂不实现。
