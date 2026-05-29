# 边侧代码待完成项

> 基于 2026-05-29 审计，逐条核实代码后重新排定优先级。

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

#### 1. LWT / device_offline 订阅未实现 ⬆️ 原 P2

**文件**: `main.py:206-211`

端侧已正确设置 LWT（`app.cpp:83` 指定 `edge/device/offline/{device_id}`），Broker 在端侧断线时自动发布离线消息。但边侧 5 个 MQTT 订阅中唯独缺了 `edge/device/offline/#`，导致端侧异常断线时边侧无感知，无法做 session 清理和告警。

**改动**:
- `main.py` 新增 `on_device_offline` 回调
- 添加 `await mqtt.subscribe("edge/device/offline/#", 1, on_device_offline)`
- 回调中：日志记录 + 标记对应 device 离线 + 可选告警

---

### P2 — 完善

#### 2. report_generate 聚合数据未接入 ⬇️ 原 P1

**文件**: `scheduler.py:91-123` (dispatch 方法)

`_build_cloud_request()` (line 349)、`_build_report_aggregate()` (line 367)、`_person_count_summary()` (line 374)、`_attendance_summary()` (line 398)、`_behavior_summary()` (line 416) **全部已实现**。但 `dispatch()` 在构造云端请求时**未调用** `_build_cloud_request()`，而是内联构建 payload，导致 `params.aggregate` 为空 `{}`：

```python
# scheduler.py line 108-117 — 当前代码
payload = {
    ...
    "params": {},   # ← 应为 await self._build_cloud_request(task)
}
```

**改动**: `dispatch()` 中 cloud 分支改为 `payload = await self._build_cloud_request(task)`。

---

| # | 项 | 说明 |
|---|---|---|
| 3 | gRPC 客户端未实现 | `grpc_client.py` — `_report()` 和 `heartbeat()` 方法体为 `pass`。需定义 proto + 生成 stub + 实现 ReportStatus/Heartbeat RPC |
| 4 | Experiment 模块未接入 | `experiment.py` 实现完整（三策略各 N 次模拟），但 `main.py` 不创建实例、不传入 `create_router`。`routes.py:129-134` 返回硬编码空响应 |

---

## 修复顺序建议

```
1. P1-1  LWT 订阅          ← 一行 subscribe + 回调，打通端侧断线感知
2. P2-2  report_generate   ← dispatch() 一行改动，聚合数据流入云端
3. P2-3  gRPC 客户端       ← proto 编译 + 真实 RPC 调用
4. P2-4  Experiment 接入   ← main.py 创建实例 + routes 连线
```
