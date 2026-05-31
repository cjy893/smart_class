# 云端代码待完成项

> 基于 2026-05-29 架构审计。P0 为阻塞长期运行稳定性的项，P1 为核心功能缺失，P2 为完善项。

## 已确认可工作

- MQTT 异步通信 (connect_async + loop_start + 自动重连)
- 任务接收 + 类型路由 (behavior_analyze / report_generate)
- 幂等去重 (task_id 缓存 + 重复任务直接返回缓存)
- YOLOv5m ONNX 人体检测 (OpenCV DNN)
- 启发式规则行为分类 (hand_up / standing / head_down / talking)
- JSON + HTML 双格式报告生成 + HTTP 静态文件服务
- gRPC 服务器 (ReportStatus + Heartbeat + Ack)
- 云端自监控 (CPU/内存/队列深度 30s MQTT 上报)
- 配置严格校验 + 非法消息优雅降级 + 优雅启停

---

## P0 — 阻塞长期运行

### 1. `_result_cache` 无界增长

**文件**: `task_handler.py:14`

**现象**: `_result_cache` 是普通 dict，无 TTL、无容量上限、无清理逻辑。每完成一个 task 就写入一条，课堂运行数小时后内存持续增长。

**改动**:
- 加 LRU 容量上限（如 1000 条）或 TTL 过期（如 300s，与边侧 dedup_window 对齐）
- 或在 `periodic_checks` 中定期清理过期条目

---

### 2. gRPC 边侧状态数据只存不消费

**文件**: `grpc_server.py:39-40`

**现象**: `latest_edge_status` 和 `latest_heartbeats` 两个 dict 持续写入，但无任何代码读取。边侧上报的状态被静默丢弃。

**期望**:
- 边侧心跳超时（如 60s 未更新）→ 日志 WARNING
- 边侧状态异常（cpu 满载、队列堆积）→ 日志 ERROR
- 可选：暴露 HTTP 端点供 Dashboard 查询边侧状态

**改动**:
- `grpc_server.py` 新增 `get_edge_status(edge_id) → dict | None`
- `main.py` 或 `app.py` 的 `periodic_checks` 中检查心跳超时并告警
- 可选：`http_server.py` 新增 `GET /api/v1/edges/status` 端点

---

## P1 — 核心功能缺失

### 3. 缺少健康检查端点

**现象**: 边侧有 FastAPI `/api/v1/nodes/status` 等完整 API，云端只有一个报告文件 HTTP 服务器。运维时无法快速判断云端是否健康。

**期望**:
- `GET /api/v1/health` 返回 `{"status": "ok", "cloud_id": "cloud-main", "uptime": ..., "mqtt_connected": true, "model_loaded": true}`
- `GET /api/v1/status` 返回完整状态（负载、队列深度、连接的边侧列表、最近任务统计）

**改动**:
- `http_server.py` 扩展路由，新增 API 端点（或新建 `api/` 模块）
- `CloudApp` 暴露状态查询接口

---

### 4. `CloudApp.stop()` 不停止 task_handler

**文件**: `app.py:77-82`

**现象**: stop 流程缺少 `task_handler` 的显式清理。当前靠 MQTT disconnect 隐式断开订阅，逻辑不够显式。

**改动**:
- `CloudTaskHandler` 新增 `stop()` 方法，取消 MQTT 订阅
- `CloudApp.stop()` 中调用 `await self.task_handler.stop()`

---

### 5. `ModelLoader` 是空壳

**文件**: `app.py:16-18`

**现象**: `preload()` 只检查文件存在，不实际加载模型到内存。真正的模型加载在 BehaviorEngine 首次推理时懒加载，首次推理冷启动延迟较高。

**期望**: 启动时即加载 ONNX 模型到 OpenCV DNN，确保首次推理延迟可预期。

**改动**:
- `BehaviorEngine` 暴露 `preload()` 方法，内部调用 `detector._load_net()`
- `CloudApp.start()` 中先初始化 behavior_engine 再调用 `behavior_engine.preload()`
- 删掉现有的 `ModelLoader` 类

---

## P2 — 完善

### 6. `BehaviorEngine.analyze_base64` 死代码

**文件**: `behavior_engine.py:68`

**现象**: base64 解码已在 `task_handler._execute()` 完成，`analyze_base64` 方法无人调用。

**改动**: 删除 `analyze_base64` 方法，或将其移到 `task_handler` 中作为辅助。

---

### 7. `status_reporter.py:37` 类型注解不兼容 Python 3.9

**文件**: `status_reporter.py:37`

**现象**: `self._task: asyncio.Task | None = None` 使用 `X | None` 语法，Python 3.9 不支持。当前 myenv 是 Python 3.11 暂不受影响，但架构文档 §12 注明 PC 平台 "Python 3.9+"。

**改动**: 改为 `from typing import Optional` + `Optional[asyncio.Task]`

---

| # | 项 | 优先级 | 影响 |
|---|---|---|---|
| 6 | `analyze_base64` 死代码 | P2 | 代码清洁度 |
| 7 | `X \| None` 类型注解 | P2 | Python 3.9 兼容性 |

---

## 跨层依赖

以下项不在云端代码范围内，但云端的部分功能依赖边侧先完成：

| 依赖项 | 位置 | 说明 |
|---|---|---|
| report_generate 边侧聚合转发 | `edge/src/scheduler.py` | 边侧的 `_run_report_generate()` 未实现（TODO_EDGE #4），云端已就绪但收不到聚合数据 |
| 边侧 gRPC 客户端 | `edge/src/grpc_client.py` | 边侧未向云端的 gRPC Server 上报状态（TODO_EDGE #6），云端 gRPC Server 已就绪但无请求 |
