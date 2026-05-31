# 云边端协同推理系统 — 系统架构设计

## 1. 项目目录结构

```
/mnt/e/edge_compute/
├── CONTEXT.md                          # 领域词汇表
├── docs/
│   ├── REQUIREMENTS.md                 # 需求规格
│   └── ARCHITECTURE.md                 # 本设计文档
│
├── proto/
│   └── edge_report.proto               # gRPC: EdgeReport service
│
├── device/                             # Milk-V Duo256M (C++, TDL SDK)
│   ├── CMakeLists.txt
│   ├── config/
│   │   └── milkv_config.yaml
│   ├── src/
│   │   ├── main.cpp                    # 入口
│   │   ├── app.cpp/.h                  # 主控循环
│   │   ├── config.cpp/.h               # YAML 配置加载
│   │   ├── task_queue.cpp/.h           # FIFO 任务队列 (深度1)
│   │   ├── inference_engine.cpp/.h     # TDL SDK YOLOv5n 封装
│   │   ├── mqtt_client.cpp/.h          # MQTT (paho.mqtt.c)
│   │   ├── http_server.cpp/.h          # 极简 HTTP Server (libmicrohttpd)
│   │   ├── gpio_handler.cpp/.h         # 按键 + 500ms 防抖
│   │   ├── camera.cpp/.h               # V4L2 摄像头采集
│   │   ├── offline_cache.cpp/.h        # 离线 JSON 缓存
│   │   └── heartbeat.cpp/.h            # 5s 心跳
│   └── web/
│       └── index.html                  # 端侧 Web 单页应用
│
├── edge/                               # Atlas 200I DK A2 (Python)
│   ├── config/
│   │   ├── edge_config.yaml
│   │   └── schedule.json               # 课表
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py                     # 入口，启动顺序编排
│   │   ├── mqtt_client.py              # MQTT 客户端 (paho-mqtt)
│   │   ├── scheduler.py                # 调度引擎
│   │   ├── policy.py                   # 三种调度策略
│   │   ├── task_manager.py             # Task 生命周期管理 + 超时监控
│   │   ├── session_manager.py          # Session 生命周期
│   │   ├── schedule_loader.py          # 课表 JSON 加载 + 定时检查
│   │   ├── face_lib.py                 # 人脸库管理 + 特征预提取
│   │   ├── inference/
│   │   │   ├── __init__.py
│   │   │   ├── inference_service.py    # MindX SDK mxVision 推理服务封装 (模型加载/推理/卸载)
│   │   │   ├── face_engine.py          # RetinaFace + ArcFace (调用 MindX SDK)
│   │   │   └── behavior_engine.py      # YOLOv5m + 规则引擎 (调用 MindX SDK)
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── connection.py           # SQLite 连接管理 (WAL 模式)
│   │   │   ├── models.py               # 数据模型 (dataclass)
│   │   │   ├── repository.py           # CRUD 操作
│   │   │   └── schema.sql              # DDL
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── server.py               # FastAPI 应用
│   │   │   ├── routes.py               # REST 路由
│   │   │   └── sse.py                  # SSE 推送
│   │   ├── grpc_client.py              # gRPC → 云端上报
│   │   └── experiment.py               # 实验模式 benchmark
│   └── data/
│       ├── face_lib/
│       │   ├── students.json           # 花名册
│       │   ├── photos/                 # 学生照片
│       │   └── embeddings/             # 预提取特征向量 (.npy)
│       └── edge.db                     # SQLite 数据库
│
├── cloud/                              # PC (Python)
│   ├── config/
│   │   └── cloud_config.yaml
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py                     # 入口
│   │   ├── mqtt_client.py              # MQTT 客户端
│   │   ├── grpc_server.py              # gRPC 服务端
│   │   ├── inference/
│   │   │   ├── __init__.py
│   │   │   └── behavior_engine.py      # YOLOv5m + 规则引擎
│   │   ├── report/
│   │   │   ├── __init__.py
│   │   │   └── generator.py            # JSON + HTML 报告生成
│   │   └── status_reporter.py          # 30s MQTT 状态上报
│   └── data/
│       └── reports/                    # 生成的报告文件
│
└── scripts/                            # 工具脚本
    ├── init_edge_db.py                 # SQLite 建库
    └── generate_students.py            # 花名册生成
```

---

## 2. 三层组件与职责

### 2.1 端侧 (Milk-V Duo256M) — C++ / TDL SDK

| 模块 | 职责 |
|---|---|
| **App** | 主循环：心跳定时器 → 摄像头采集 → person_count 推理 → 结果上报 → 检查任务队列 |
| **Config** | 加载 YAML 配置 (device_id, MQTT broker, interval 等) |
| **TaskQueue** | FIFO 队列(深度1)，线程安全。push() 满时返回 false，pop() 阻塞 |
| **InferenceEngine** | TDL SDK YOLOv5n 封装，`detect_persons(frame) → int` |
| **MqttClient** | 连接 Broker，pub/sub 管理，LWT 设置，QoS 按 topic 区分 |
| **HttpServer** | 极简 HTTP(端口8080)，GET /api/status, /api/last_result, /api/screenshot; POST /api/action/* |
| **GpioHandler** | GPIO 轮询 / CLI 模拟，500ms 防抖，2s 长按判定 |
| **Camera** | V4L2 采集，YUV→RGB 转换，JPEG 编码截图 |
| **OfflineCache** | JSON 行文件追加 person_count 结果，重连后批量推送并删除 |
| **Heartbeat** | 5s 定时器，构造心跳 JSON(QoS 0) |

**端侧状态机**:
```
INIT → CONNECTING(连Broker) → ONLINE(发上线宣告) → ACTIVE(session中) / IDLE(非上课)
ACTIVE → DEGRADED(边侧离线, 纯本地) → ACTIVE(边侧恢复)
ANY → OFFLINE(断网, person_count本地+缓存)
```

### 2.2 边侧 (Atlas 200I DK A2) — Python

| 模块 | 职责 |
|---|---|
| **main** | 启动顺序编排：配置→CANN/MindX SDK init→SQLite→模型预加载(.om)→人脸库→课表→MQTT→调度引擎→FastAPI→gRPC |
| **MqttClient** | 订阅端侧 topic + 云端 result topic；发布调度指令 + 云端 task request |
| **Scheduler** | 接收 Task 请求，按策略决策目标层，转发上云或入本地队列 |
| **Policy** | GreedyNearby / LoadBalance / Adaptive 三种策略 |
| **TaskManager** | Task 生命周期：创建→状态变更→超时监控。按 task_id 幂等去重 |
| **SessionManager** | Session CRUD：上课创建(active)，下课结束(completed)。`ended_at IS NULL` 查活跃 |
| **ScheduleLoader** | 加载 schedule.json，每分钟检查，上课/下课触发回调 |
| **FaceLib** | 扫描 photos/ 目录→预提取 embeddings→缓存 .npy→变化检测(hash) |
| **InferenceService** | MindX SDK mxVision 初始化/去初始化；管理所有 Model 对象生命周期 |
| **FaceEngine** | 通过 MindX SDK 调用 RetinaFace.om + ArcFace.om；余弦相似度匹配人脸库 |
| **BehaviorEngine** | 通过 MindX SDK 调用 YOLOv5m.om + 规则引擎(举手/起立/低头/交谈) |
| **db.connection** | SQLite 连接管理，WAL 模式 |
| **db.models** | Session / Task / PersonCount / AttendanceRecord / BehaviorRecord dataclass |
| **db.repository** | 各实体 CRUD |
| **api.server** | FastAPI 应用 + CORS |
| **api.routes** | REST API endpoints (见 REQUIREMENTS 6.5) |
| **api.sse** | SSE 推送实时数据 |
| **GrpcClient** | 每 30s 向云端 ReportStatus + Heartbeat |
| **Experiment** | Benchmark：预录图像→三策略各发 N 个模拟任务→统计 CDF |

### 2.3 云端 (PC) — Python

| 模块 | 职责 |
|---|---|
| **main** | 启动顺序：配置→模型预加载→连 Broker→gRPC Server→MQTT 状态上报 |
| **MqttClient** | 订阅 `cloud/task/request/#`，发布 `cloud/task/result/{device_id}` + `cloud/status/report` |
| **GrpcServer** | 接收边侧 StatusReport + Heartbeat，返回 Ack |
| **BehaviorEngine** | YOLOv5m 人体检测 + 启发式规则(与边侧同模型) |
| **ReportGenerator** | 接收边侧聚合数据→格式化 JSON + HTML→存储→返回 report_url |
| **StatusReporter** | 30s 定时器，发布 `cloud/status/report` (QoS 0) |

---

## 3. SQLite Schema (边侧)

```sql
-- Session: 课堂记录
CREATE TABLE session (
    session_id   TEXT PRIMARY KEY,                -- {device_id}_{date}_{start_time}
    device_id    TEXT NOT NULL,
    course_name  TEXT,
    teacher      TEXT,
    class_name   TEXT,
    start_time   TEXT NOT NULL,                   -- ISO8601
    ended_at     TEXT,                            -- NULL = 活跃中
    status       TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'completed'
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Task: 任务记录 (person_count 不入此表)
CREATE TABLE task (
    task_id        TEXT PRIMARY KEY,
    task_type      TEXT NOT NULL,                 -- face_attendance | behavior_analyze | report_generate
    trigger_source TEXT NOT NULL,                 -- system_timer | user_button | dashboard_manual
    session_id     TEXT NOT NULL REFERENCES session(session_id),
    device_id      TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'CREATED',
    target_layer   TEXT,                          -- 'edge' | 'cloud'
    result_json    TEXT,                          -- JSON string
    metrics_json   TEXT,                          -- JSON string
    created_at     TEXT NOT NULL,
    completed_at   TEXT,
    timeout_at     TEXT,
    attempt        INTEGER DEFAULT 1              -- face_attendance 多次签到序号
);

-- PersonCount: 人数统计采样点
CREATE TABLE person_count (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES session(session_id),
    device_id   TEXT NOT NULL,
    count       INTEGER NOT NULL,
    timestamp   TEXT NOT NULL,                    -- ISO8601
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_person_count_session ON person_count(session_id, timestamp);

-- PersonCountAgg: 每课聚合摘要 (下课时生成)
CREATE TABLE person_count_aggregate (
    session_id    TEXT PRIMARY KEY REFERENCES session(session_id),
    avg_count     REAL,
    max_count     INTEGER,
    min_count     INTEGER,
    sample_count  INTEGER,
    aggregated_at TEXT NOT NULL
);

-- AttendanceRecord: 签到明细 (逐学生)
CREATE TABLE attendance_record (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES session(session_id),
    task_id      TEXT NOT NULL REFERENCES task(task_id),
    student_id   TEXT NOT NULL,
    student_name TEXT NOT NULL,
    status       TEXT NOT NULL,                   -- 'present' | 'absent' | 'unknown'
    confidence   REAL,
    timestamp    TEXT NOT NULL
);
CREATE INDEX idx_attendance_session ON attendance_record(session_id);

-- BehaviorRecord: 行为分析结果
CREATE TABLE behavior_record (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL REFERENCES session(session_id),
    task_id        TEXT NOT NULL REFERENCES task(task_id),
    executed_layer TEXT NOT NULL,                 -- 'edge' | 'cloud'
    behavior_type  TEXT NOT NULL,                 -- hand_up | standing | head_down | talking
    count          INTEGER NOT NULL,
    timestamp      TEXT NOT NULL
);
```

> Device 由边侧**内存维护**（在线状态 + 最后心跳时间），不建表。重启后靠端侧上线宣告重建。

---

## 4. MQTT Topic 交互矩阵

| Topic | 发布者 | 订阅者 | QoS | 说明 |
|---|---|---|---|---|
| `edge/task/request/{device_id}` | 端 | 边(调度引擎) | 1 | 任务请求 |
| `edge/task/result/{device_id}` | 边/云 | 端 | 1 | 边侧或云端执行结果 |
| `cloud/task/request/{device_id}` | 边(调度引擎) | 云 | 1 | 调度上云的任务 |
| `cloud/task/result/{device_id}` | 云 | 边 + 端 | 1 | 云端结果(双订阅) |
| `edge/device/online/{device_id}` | 端 | 边 | 1 (retained) | 上线宣告 |
| `edge/device/offline/{device_id}` | Broker(LWT) | 边 | 1 (retained) | 异常断线 |
| `edge/heartbeat/{device_id}` | 端 | 边 | 0 | 5s 心跳 |
| `cloud/status/report` | 云 | 边(调度引擎) | 0 | 30s 云端负载 |
| `edge/status/person_count/{device_id}` | 端 | 边 | 0 | 人数统计结果 |
| `edge/schedule/command/{device_id}` | 边 | 端 | 1 | 调度指令(策略切换/session恢复) |

---

## 5. gRPC Proto

```protobuf
syntax = "proto3";

service EdgeReport {
  rpc ReportStatus(StatusReport) returns (Ack);
  rpc Heartbeat(HeartbeatRequest) returns (Ack);
}

message StatusReport {
  string edge_id = 1;
  double cpu_percent = 2;
  double npu_percent = 3;
  double memory_mb = 4;
  int32 task_queue_depth = 5;
  int32 connected_devices = 6;
  string timestamp = 7;
}

message HeartbeatRequest {
  string edge_id = 1;
  string timestamp = 2;
}

message Ack { bool ok = 1; }
```

---

## 6. 核心数据流

### 6.1 person_count 流程

```
[端侧 Camera] → 采集帧
  → [InferenceEngine] YOLOv5n 检测 → count
  → [端侧内存] 构造 result_json {task_id, count, timestamp, metrics}
  → [MqttClient] PUBLISH edge/status/person_count/{device_id} (QoS 0)
  → [边侧 MqttClient] 接收
  → [db.repository] INSERT INTO person_count
  → [端侧 HttpServer] 更新内存状态 → /api/status 返回最新人数
```

### 6.2 face_attendance 流程

```
[教师按键2短按] → [GpioHandler] 防抖 → 回调
  → [端侧 App] 生成 task_id, 裁剪人脸区域 (base64)
  → [MqttClient] PUBLISH edge/task/request/{device_id} (QoS 1)
  → [边侧 Scheduler] 接收, 幂等检查
  → [Scheduler] 决策: face_attendance → 边侧 (硬约束, 人脸库在边侧)
  → [边侧 TaskManager] 任务入队 (串行队列)
  → [FaceEngine] RetinaFace 检测 + ArcFace 特征 + 余弦匹配
  → [db.repository] INSERT task + INSERT attendance_record (逐学生)
  → [MqttClient] PUBLISH edge/task/result/{device_id} (QoS 1)
  → [端侧 MqttClient] 接收 → 更新内存 last_result
  → [端侧 Web] /api/last_result 返回签到名单 {present, absent, unknown}
```

### 6.3 behavior_analyze 流程 (调度到云)

```
[教师按键2长按2s] → [GpioHandler] → 回调
  → [端侧 App] 生成 task_id, 全帧 base64
  → [MqttClient] PUBLISH edge/task/request/{device_id} (QoS 1)
  → [边侧 Scheduler] 接收, 幂等检查
  → [Scheduler.policy] 打分, 决策 → cloud
  → [MqttClient] PUBLISH cloud/task/request/{device_id} (QoS 1, 含全帧)
  → [云端 MqttClient] 接收
  → [云端 BehaviorEngine] YOLOv5m + 规则引擎 → result_json
  → [云端 MqttClient] PUBLISH cloud/task/result/{device_id} (QoS 1)
  → [边侧 MqttClient] 接收 → db.repository INSERT task + behavior_record
  → [端侧 MqttClient] 接收 → 更新内存 last_result
```

### 6.4 behavior_analyze 流程 (调度到边)

```
同上至 [Scheduler.policy] 决策 → edge
  → [边侧 TaskManager] 任务入队 (串行队列)
  → [边侧 BehaviorEngine] YOLOv5m + 规则引擎 → result_json
  → [db.repository] INSERT task + behavior_record
  → [MqttClient] PUBLISH edge/task/result/{device_id} (QoS 1)
  → [端侧 MqttClient] 接收 → 更新内存 last_result
```

### 6.5 report_generate 流程

```
[下课时间到] OR [教师按键3短按]
  → [SessionManager] 判断触发类型:
      下课触发 → 最终报告 (end session, status='completed')
      按键触发 → 中期报告 (session 继续)
  → [db.repository] 聚合 Session 数据:
      person_count 摘要 + attendance 最新 + behavior 汇总
  → [MqttClient] PUBLISH cloud/task/request/{device_id} (QoS 1, 附带聚合数据)
  → [云端 ReportGenerator] 生成 JSON + HTML → 存储到 data/reports/
  → [云端 MqttClient] PUBLISH cloud/task/result/{device_id} (QoS 1, 含 report_url + summary)
  → [边侧 MqttClient] 接收 → db.repository INSERT task
  → [端侧 MqttClient] 接收 → 更新内存 last_result (仅摘要数字)
  → [Dashboard] 通过边侧 HTTP GET /reports/{filename} 获取完整 HTML 报告
```

### 6.6 端侧重启恢复流程

```
[端侧重启] → [Config] 加载 device_id
  → [MqttClient] 连接 Broker + LWT 设置
  → PUBLISH edge/device/online/{device_id} (QoS 1, retained)
  → [边侧 MqttClient] 收到上线宣告
  → [SessionManager] SELECT * FROM session WHERE ended_at IS NULL AND device_id = ?
  → 若有活跃 session:
    → [MqttClient] PUBLISH edge/schedule/command/{device_id}
       {command: "session_restore", session_id: "...", policy: "adaptive"}
  → [端侧 MqttClient] 接收恢复指令
  → [端侧 App] 设 session_id, 启动 person_count 定时器
  → 从当前时刻开始, 不补算丢失时段
```

### 6.7 云端离线降级流程

```
[边侧 Scheduler] 连续 60s 未收到 cloud/status/report
  → 标记 cloud_status = OFFLINE
  → behavior_analyze 到达时:
      Scheduler.policy 自动跳过 cloud 选项, 决策 → edge
  → report_generate 到达时:
      Scheduler 直接 REJECTED (云独有能力)
  → 端侧 Web 提示 "云端服务不可用"
  → cloud/status/report 恢复 → 标记 cloud_status = ONLINE
```

---

## 7. 配置文件

### 7.1 端侧 `device/config/milkv_config.yaml`

```yaml
device_id: "classroom-301"
mqtt:
  broker_host: "192.168.1.100"
  broker_port: 1883
  keepalive_seconds: 10
person_count:
  interval_seconds: 2
web_server:
  port: 8080
camera:
  device: "/dev/video0"
  width: 640
  height: 480
  screenshot_interval_seconds: 1
task:
  queue_depth: 1
  debounce_ms: 500
  long_press_ms: 2000
inference:
  model_path: "/data/models/yolov5n.rknn"
heartbeat:
  interval_seconds: 5
offline:
  cache_path: "/tmp/offline_cache.jsonl"
```

### 7.2 边侧 `edge/config/edge_config.yaml`

```yaml
device_id: "edge-atlas-01"
mqtt:
  broker_host: "localhost"
  broker_port: 1883
scheduler:
  policy: "adaptive"                          # greedy_nearby | load_balance | adaptive
  timeout_person_count_ms: 3000
  timeout_face_attendance_ms: 15000
  timeout_behavior_analyze_ms: 30000
  timeout_report_generate_ms: 30000
  cloud_offline_timeout_s: 60
  dedup_window_seconds: 300
api:
  host: "0.0.0.0"
  port: 8000
grpc:
  cloud_address: "192.168.1.200:50051"
  report_interval_seconds: 30
paths:
  face_lib: "/mnt/e/edge_compute/edge/data/face_lib"
  schedule: "/mnt/e/edge_compute/edge/config/schedule.json"
  sqlite_db: "/mnt/e/edge_compute/edge/data/edge.db"
  models: "/data/models"
  mindx_home: "/usr/local/Ascend/mindx_sdk"   # MindX SDK 安装路径
inference:
  face_detection_model: "/data/models/retinaface.om"
  face_recognition_model: "/data/models/arcface.om"
  behavior_model: "/data/models/yolov5m.om"
  preload_models: true
  device_id: 0                                 # Ascend 310P NPU 设备 ID
device:
  heartbeat_timeout_seconds: 15
experiment:
  simulated_task_count: 100
  test_images_dir: "/data/benchmark_images"
```

### 7.3 云端 `cloud/config/cloud_config.yaml`

```yaml
cloud_id: "cloud-main"
mqtt:
  broker_host: "192.168.1.100"
  broker_port: 1883
grpc:
  listen_address: "0.0.0.0:50051"
paths:
  models: "../data/models"
  reports: "../data/reports"
behavior:
  use_rule_engine: true
  model_path: "../data/models/yolov5m.onnx"
status_report:
  interval_seconds: 30
```

---

## 8. 启动顺序

```
Step 1: Atlas - Mosquitto Broker 启动 (systemctl start mosquitto)

Step 2: Atlas - 边侧服务启动
  2.1  加载 edge_config.yaml
  2.2  MindX SDK 初始化 (source set_env.sh → base.mx_init())
  2.3  SQLite 初始化 (CREATE TABLE IF NOT EXISTS)
  2.4  模型预加载到 NPU (RetinaFace.om, ArcFace.om, YOLOv5m.om 通过 MindX SDK)
  2.5  人脸库扫描 + 特征预提取 (检查 embeddings/ 缓存, 仅变更时重提取)
  2.6  课表加载 (schedule.json)
  2.7  ScheduleLoader 启动定时检查 (每分钟)
  2.8  SessionManager 扫描活跃 session (ended_at IS NULL, 恢复用)
  2.9  MQTT 客户端连接 + 订阅所有 topic
  2.10 调度引擎启动
  2.11 gRPC 客户端启动 (连接云端)
  2.12 FastAPI 启动 (端口 8000)

Step 3: PC - 云端服务启动
  3.1  加载 cloud_config.yaml
  3.2  模型预加载 (YOLOv5m)
  3.3  MQTT 客户端连接 + 订阅 cloud/task/request/#
  3.4  gRPC Server 启动 (端口 50051)
  3.5  StatusReporter 启动 (30s MQTT 上报)

Step 4: Milk-V - 端侧服务启动
  4.1  加载 milkv_config.yaml (含静态 device_id)
  4.2  模型预加载 (YOLOv5n)
  4.3  MQTT 客户端连接 + LWT 设置
  4.4  发布上线宣告 edge/device/online/{device_id}
  4.5  等待边侧下发 session 恢复指令 (若有活跃 session)
  4.6  启动心跳定时器 (5s)
  4.7  启动 person_count 定时器 (若在 session 中)
  4.8  启动 HTTP Server (端口 8080)
  4.9  启动 GPIO 按键监听
  4.10 进入主循环
```

---

## 9. 关键 Python 模块接口

以下为边侧核心模块的公开接口定义，具体实现在编码阶段完成。

### 9.1 Scheduler (调度引擎)

```python
class Scheduler:
    def __init__(self, policy: Policy, mqtt: MqttClient, task_mgr: TaskManager) -> None
    async def handle_task_request(self, message: dict) -> None    # MQTT 回调入口
    async def dispatch(self, task: Task, target: str) -> None     # 路由到 'edge' 或 'cloud'
    async def handle_cloud_result(self, message: dict) -> None    # 云端结果回调
    def get_stats(self) -> dict                                   # 实时调度统计
```

### 9.2 Policy (调度策略)

```python
class SchedulingContext:
    edge_load: float          # 0-100
    cloud_load: float         # 0-100
    edge_queue_depth: int
    cloud_queue_depth: int
    edge_cloud_rtt_ms: float
    device_edge_rtt_ms: float

class Policy(ABC):
    @abstractmethod
    def decide(self, task: Task, context: SchedulingContext) -> str  # → 'edge' | 'cloud'

class GreedyNearbyPolicy(Policy):     # 能边不云
    ...

class LoadBalancePolicy(Policy):      # 每层能力分数, 选最空闲
    ...

class AdaptivePolicy(Policy):         # 0.5*延迟 + 0.3*精度 + 0.2*负载 加权
    ...
```

### 9.3 SessionManager (课堂生命周期)

```python
class SessionManager:
    def __init__(self, repo: SessionRepository, mqtt: MqttClient) -> None
    async def start_session(self, schedule_entry: dict) -> Session
    async def end_session(self, session_id: str) -> Session        # → 触发 report_generate
    async def get_active_session(self, device_id: str) -> Optional[Session]
    async def recover_active_sessions(self) -> list[Session]       # 重启恢复
    def is_class_time(self, device_id: str) -> bool
```

### 9.4 TaskManager (任务生命周期)

```python
class TaskManager:
    def __init__(self, repo: TaskRepository, mqtt: MqttClient) -> None
    async def create_task(self, msg: dict) -> Task
    async def update_status(self, task_id: str, status: TaskStatus) -> None
    async def handle_result(self, task_id: str, result: dict) -> None
    def is_duplicate(self, task_id: str) -> bool                   # 幂等去重
    async def start_timeout_monitor(self, task: Task) -> None
    def get_queue_depth(self) -> int
```

### 9.5 Inference Engines (基于 MindX SDK mxVision)

```python
class InferenceService:
    """MindX SDK mxVision 全局服务封装，管理 NPU 设备生命周期。"""
    def __init__(self, device_id: int = 0) -> None
    async def init(self) -> None                     # base.mx_init() + 加载所有 .om 模型
    async def deinit(self) -> None                   # base.mx_deinit()
    def get_model(self, name: str) -> base.Model     # 获取已加载的模型对象

class FaceEngine:
    """人脸检测 + 特征提取。通过 InferenceService 获取 MindX Model。"""
    async def detect(self, image: bytes) -> list[FaceBox]          # RetinaFace.om
    async def extract_features(self, face_crop: bytes) -> np.ndarray  # ArcFace.om
    async def recognize(self, image: bytes, face_lib: FaceLib) -> FaceResult
    # FaceResult: {present: list[Student], absent: list[Student], unknown: int}

class BehaviorEngine:
    """人体检测 + 规则引擎行为分类。通过 InferenceService 获取 YOLOv5m Model。"""
    async def analyze(self, image: bytes) -> BehaviorResult
    # BehaviorResult: {hand_up: int, standing: int, head_down: int, talking: int, total: int}
```

> MindX SDK 的 `model.infer()` 是同步调用。所有 Engine 方法内部通过 `asyncio.to_thread()` 包装，避免阻塞 FastAPI 事件循环。

### 9.6 Repository 层

```python
class SessionRepository:
    async def create(self, session: Session) -> str
    async def end(self, session_id: str, ended_at: str) -> None
    async def get_active(self, device_id: str) -> Optional[Session]
    async def list_active(self) -> list[Session]

class TaskRepository:
    async def create(self, task: Task) -> str
    async def update(self, task_id: str, **kwargs) -> None
    async def get(self, task_id: str) -> Optional[Task]
    async def exists(self, task_id: str) -> bool
    async def get_latest_attendance_attempt(self, session_id: str) -> int

class PersonCountRepository:
    async def insert(self, record: PersonCount) -> int
    async def get_by_session(self, session_id: str) -> list[PersonCount]
    async def aggregate_and_prune(self, session_id: str) -> PersonCountAggregate

class AttendanceRepository:
    async def insert_batch(self, records: list[AttendanceRecord]) -> None
    async def get_latest_by_session(self, session_id: str) -> list[AttendanceRecord]

class BehaviorRepository:
    async def insert_batch(self, records: list[BehaviorRecord]) -> None
    async def get_summary_by_session(self, session_id: str) -> dict[str, int]
```

---

## 10. 任务类型与执行层约束

| 任务类型 | 端 | 边 | 云 | 调度决策 |
|---|---|---|---|---|
| `person_count` | ✅ (硬约束) | — | — | 透传, 不参与调度 |
| `face_attendance` | — | ✅ (硬约束, 人脸库) | — | 无决策空间 |
| `behavior_analyze` | — | ✅ YOLOv5m | ✅ YOLOv5m | **v1 唯一决策空间** |
| `report_generate` | — | — | ✅ (硬约束, 格式化) | 无决策空间 |

---

## 11. MQTT 消息格式汇总

### 11.1 任务请求 `edge/task/request/{device_id}`

```json
{
  "task_id": "uuid-or-snowflake",
  "task_type": "face_attendance|behavior_analyze|report_generate",
  "trigger_source": "user_button|system_timer",
  "session_id": "classroom-301_2026-05-26_08-00",
  "device_id": "classroom-301",
  "created_at": "2026-05-26T08:15:02.123",
  "image": "<base64>",
  "params": {}
}
```

### 11.2 任务结果 `{edge,cloud}/task/result/{device_id}`

按 task_type 使用对应的 result schema (见 REQUIREMENTS 3.5)。

### 11.3 人数上报 `edge/status/person_count/{device_id}`

```json
{
  "task_id": "...",
  "device_id": "classroom-301",
  "session_id": "classroom-301_2026-05-26_08-00",
  "result": { "count": 32, "timestamp": "2026-05-26T08:15:02" },
  "metrics": { "inference_latency_ms": 120 }
}
```

### 11.4 心跳 `edge/heartbeat/{device_id}`

```json
{
  "device_id": "classroom-301",
  "timestamp": "2026-05-26T08:15:02",
  "status": "online",
  "load": { "cpu_percent": 45.2, "npu_percent": 30.1, "memory_mb": 128 },
  "task_queue_depth": 0,
  "bandwidth_bytes_sent": 1048576,
  "current_session_id": "classroom-301_2026-05-26_08-00",
  "current_policy": "adaptive"
}
```

### 11.5 云端状态上报 `cloud/status/report`

```json
{
  "cloud_id": "cloud-main",
  "timestamp": "2026-05-26T08:15:02",
  "load": { "cpu_percent": 55.0, "gpu_percent": 40.0, "memory_mb": 4096 },
  "task_queue_depth": 0,
  "status": "online"
}
```

### 11.6 调度指令 `edge/schedule/command/{device_id}`

```json
{
  "command": "session_restore|policy_change",
  "session_id": "...",
  "policy": "adaptive"
}
```

---

## 12. 平台注意事项

| 平台 | 要点 |
|---|---|
| **Milk-V Duo256M** | 256MB DDR3, CVITEK CV1812H. TDL SDK 提供 YOLOv5n 量化(.rknn). C++ 交叉编译. HTTP Server 用 libmicrohttpd. MQTT 用 paho.mqtt.c. YAML 用 yaml-cpp |
| **Atlas 200I DK A2** | Ascend 310P NPU. **MindX SDK mxVision** 提供推理 Pipeline/Model API. 模型需转 .om 格式 (ATC 工具). **Python 3.9 硬性要求**. FastAPI + uvicorn. paho-mqtt + grpcio + OpenCV + NumPy. 安装顺序: CANN → MindX SDK → Python wheel |
| **PC (Cloud)** | Python 3.9+. ONNX Runtime 或 OpenCV DNN. paho-mqtt + grpcio. Jinja2 报告模板 |

---

## 13. 实施阶段建议

| 阶段 | 内容 | 依赖 |
|---|---|---|
| **Phase 1 — 基础设施** | proto 定义, SQLite schema.sql, YAML 配置模板, MQTT topic 测试 | 无 |
| **Phase 2 — 边侧核心** | MQTT client + DB + Session/Schedule + 调度引擎 + FastAPI skeleton | Phase 1 |
| **Phase 3 — 云端** | MQTT client + gRPC server + behavior engine + report generator | Phase 1 |
| **Phase 4 — 端侧模拟** | Python 端侧模拟器, 验证全链路 MQTT 消息流 | Phase 2+3 |
| **Phase 5 — 端侧 C++** | 真实 Milk-V 交叉编译 + 硬件部署 | Phase 2+3 |
| **Phase 6 — Dashboard** | 纯 HTML + Vanilla JS + Chart.js 前端 | Phase 2 |
| **Phase 7 — 集成测试** | 实验模式 + 全链路端到端测试 | Phase 4+5+6 |

---

## 14. 验证方案

1. **单元测试**: Repository / Policy / Engine 独立测试
2. **集成测试**: Mosquitto → 边侧 → 云端 → 端侧模拟器, 全链路 MQTT 消息验证
3. **端到端场景**:
   - 上课→person_count→下课 完整生命周期
   - 按键触发签到/行为分析/报告
   - 端侧重启 mid-session 恢复
   - 云端离线 behavior_analyze 降级边侧
   - 端侧断网离线缓存+恢复
4. **实验模式**: N=100 模拟任务, 验证三种策略 CDF 差异
