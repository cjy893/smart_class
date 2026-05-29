# 边侧代码待完成项

> 基于 2026-05-28 架构审计。P0 为阻塞端到端链路的项，P1 为核心功能缺失，P2 为完善项。

## 已确认可工作

- MindX SDK 初始化 + 3 个 .om 模型预加载
- RetinaFace 人脸检测 (PriorBox decode + NMS)
- ArcFace 特征提取 (512-dim, 自相似度 1.000)
- YOLOv5m 人体检测 (NMS)
- FaceLib 人脸库 (扫描/特征提取/.npy 缓存/hash 变化检测)
- MQTT 连接 + topic 订阅
- **端侧 MQTT 连通验证通过** (online 消息正确抵达边侧 on_device_online 回调)
- SQLite 6 表建库 + WAL 模式
- 调度策略 (GreedyNearby / LoadBalance / Adaptive)
- TaskManager 幂等去重 + 超时监控
- FastAPI + SSE 全部端点
- main.py 11 步启动 clean startup 验证通过

---

## 已修复

### P0-1. person_count 数据流断链 ✓

**文件**: `scheduler.py`, `main.py`

**修复内容**:
- `HARD_CONSTRAINT_DEVICE` 已删除，person_count 不再进入调度引擎
- `handle_task_request` 中 person_count 由 `on_task_request` 过滤，走 `on_person_count` 回调直接入库

### P0-2. 调度队列串行化 ✓

**文件**: `scheduler.py`, `main.py`

**修复内容**:
- `dispatch()` edge 分支只做 `enqueue_local`，不调用 `_execute_local`
- `periodic_checks` 改为 `asyncio.create_task(scheduler._execute_local(task))` 异步消费

### P0-3. 课表下课回调 ✓

**文件**: `main.py`

**修复内容**:
- `on_class_end` → `session_mgr.end_session()` → 自动创建 `report_generate` task

### P1-5. behavior_analyze 硬约束重构 ✓

**文件**: `scheduler.py`

**修复内容**:
- 四种 task_type 各独立分支（EDGE / CLOUD / POLICY），不再共用 HARD_CONSTRAINT_DEVICE

### 端侧 MQTT Packet ID 修复 ✓

**文件**: `tdl_sdk/sample/edge_compute_device/mqtt_client.cpp`

**修复内容**:
- QoS > 0 的 PUBLISH 报文添加 2-byte Packet Identifier
- 修复前 Broker 将 payload 前 2 字节 `{"` 误解析为 Packet ID，导致消息被丢弃

---

## 待完成项

### P1 — 核心功能缺失

#### 4. report_generate 流程未实现

**文件**: `scheduler._execute_local()`, `session_manager.py`

**现象**: `REPORT_GENERATE` task 当前无对应执行逻辑（硬约束路由到 cloud，但 `_run_report_generate` 未实现）。

**期望** (架构 6.5 节):
- 聚合 Session 数据: person_count_aggregate + attendance_record 最新 + behavior_record 汇总
- MQTT PUBLISH `cloud/task/request/{device_id}` (QoS 1, 附带聚合数据)
- 支持两种触发: 下课自动触发 + 按键手动触发

**改动**:
- `scheduler.py` 新增 `_run_report_generate()` 方法
- 调用各 repository 聚合当前 session 数据
- 打包为 JSON 通过 MQTT 转发云端

---

### P2 — 完善

| # | 项 | 说明 |
|---|---|---|
| 6 | gRPC 客户端未实现 | `grpc_client.py` 只维护心跳计数，需定义 proto + 生成 stub + 实现 StatusReport/Heartbeat RPC |
| 7 | Experiment 模块未接入 | `experiment.py` 实现完整但 `main.py` 不创建实例，`routes.py` 返空 |
| 8 | LWT / device_offline 订阅 | 端侧已设 LWT，边侧 `main.py` 需订阅 `edge/device/offline/#` 处理异常断线 |
