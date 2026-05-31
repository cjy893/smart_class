# 云边端协同推理系统 —— 需求规格（智慧课堂场景）

## 1. 应用场景

智慧课堂实时分析。摄像头部署在教室后方/侧方，覆盖学生座位区。系统按课表自动运行，在上课期间持续感知课堂状态，按需在三层之间调度推理任务。

**核心逻辑**：

```
上课时间到 → 自动创建 Session + 端侧自闭环（人数统计）
教师触发签到 → 边侧人脸识别
教师触发课堂报告 / 异常行为 → 云端深度分析
下课时间到 → 自动结束 Session + 生成课堂报告
非上课时段 → 系统休眠（仅心跳）
```

## 2. 角色与用户

| 角色 | 身份 | 交互界面 | 关注点 |
|---|---|---|---|
| **教师** | 端侧操作者 | Milk-V 按键 / 手机 Web | 签到、课堂报告、实时人数 |
| **管理员** | 系统运维 | PC Dashboard | 全局状态、性能、策略对比 |

## 3. 任务模型

### 3.1 统一 Task 模型

所有执行单元均为 Task，包含 `task_id`、`task_type`、`trigger_source`、`status`、`created_at`、`session_id` 等字段。

| 字段 | 说明 |
|---|---|
| `task_id` | 全局唯一标识（UUID / 雪花ID） |
| `task_type` | `person_count` / `face_attendance` / `behavior_analyze` / `report_generate` |
| `trigger_source` | `system_timer` / `user_button` / `dashboard_manual` |
| `status` | 见 3.2 状态机 |
| `session_id` | 归属的课堂 session |
| `created_at` | 任务创建时间戳（用于全链路超时计时起点） |

### 3.2 任务状态机

```
CREATED → QUEUED → DISPATCHED → EXECUTING → COMPLETED
                  ↘ REJECTED    ↘ FAILED
```

| 状态 | 说明 |
|---|---|
| `CREATED` | 任务被触发方构造 |
| `QUEUED` | 已发布到 MQTT，等待调度引擎拉取 |
| `DISPATCHED` | 调度引擎已决策目标层，已路由 |
| `EXECUTING` | 目标层正在执行推理 |
| `COMPLETED` | 执行成功，结果已返回 |
| `REJECTED` | 调度引擎判定无层可执行（终态） |
| `FAILED` | 执行失败或全链路超时（终态，不自动重试） |

> **特例**：`person_count` 端侧自闭环，直接从 `CREATED` 跳到 `COMPLETED`，跳过中间状态。person_count 不发布 Task 请求到 MQTT，仅在端侧本地完成全流程，通过 `edge/status/person_count/{device_id}` 上报计数结果。

### 3.3 任务类型定义

| 任务类型 | 复杂度 | 描述 | 默认执行层 | 触发方式 |
|---|---|---|---|---|
| `person_count` | 低 | 检测画面中人数，按时间间隔执行 | 端侧 | 系统自动（session 期间持续） |
| `face_attendance` | 中 | 人脸检测 + 特征提取 + 身份匹配 | 边侧 | 教师按键 2 短按 |
| `behavior_analyze` | 高 | 学生行为分析（举手/起立/低头/交谈） | 云端 | 教师按键 2 长按（2s） |
| `report_generate` | 高 | 聚合全时段统计，生成课堂报告 | 云端 | 教师按键 3 短按 / 下课自动触发 |

### 3.4 任务超时

超时按全链路计时（`T_created` → `T_result`），阈值按任务类型区分：

| 任务类型 | 超时阈值（可配置） |
|---|---|
| `person_count` | 3s |
| `face_attendance` | 15s |
| `behavior_analyze` | 30s |
| `report_generate` | 30s |

超时后直接标记 `FAILED`，不自动重试，由教师重新触发。

### 3.5 任务结果格式

每种 TaskType 有独立的结果 schema，统一包含 `result` 和 `metrics` 两部分：

**person_count**：
```json
{
  "task_id": "...", "task_type": "person_count", "status": "COMPLETED",
  "result": { "count": 32, "timestamp": "2026-05-26T08:15:02" },
  "metrics": { "inference_latency_ms": 120 }
}
```

**face_attendance**：
```json
{
  "task_id": "...", "task_type": "face_attendance", "status": "COMPLETED",
  "result": {
    "present": ["张三", "李四", "王五"],
    "absent": ["赵六"],
    "unknown": 1,
    "total_expected": 33,
    "attempt": 1
  },
  "metrics": { "inference_latency_ms": 3200, "end_to_end_latency_ms": 3450 }
}
```
> 同一 session 内允许多次签到，每次以 `task_id` 区分独立存储，`attempt` 字段标识第几次。报告取最新一次结果。

**behavior_analyze**：
```json
{
  "task_id": "...", "task_type": "behavior_analyze", "status": "COMPLETED",
  "result": {
    "hand_up": 2, "standing": 1, "head_down": 5, "talking": 3,
    "total_detected": 11
  },
  "metrics": { "inference_latency_ms": 8200 }
}
```

**report_generate**：
```json
{
  "task_id": "...", "task_type": "report_generate", "status": "COMPLETED",
  "result": {
    "report_url": "/reports/classroom-301_2026-05-26_08-00.html",
    "summary": {
      "total_present": 32, "total_absent": 1,
      "peak_count": 33, "avg_count": 31.5,
      "behaviors": { "hand_up_count": 5, "head_down_ratio": 0.15 }
    }
  }
}
```

> 签到结果中 `absent = 花名册全员 - present`，`unknown` 为检测到人脸但无法匹配花名册的数量。

### 3.6 核心实体模型

边侧 SQLite 主存储包含以下实体：

| 实体 | 主键 | 关键字段 | 说明 |
|---|---|---|---|
| **Session** | `session_id` | `device_id`, `start_time`, `ended_at`, `status` | `status`: active/completed。`ended_at IS NULL` 标识活跃 session |
| **Task** | `task_id` | `task_type`, `trigger_source`, `status`, `session_id`, `created_at`, `target_layer`, `result_json`, `metrics_json` | 端侧生成 task_id。person_count 的 task 不入此表 |
| **PersonCount** | `id` | `session_id`, `count`, `timestamp` | 每次计数的原始采样点。下课时聚合，原始点仅保留当天 |
| **AttendanceRecord** | `id` | `session_id`, `task_id`, `student_id`, `student_name`, `status`, `timestamp` | `status`: present/absent/unknown。以 task_id 区分同一 session 内多次签到 |
| **BehaviorRecord** | `id` | `session_id`, `task_id`, `behavior_type`, `count`, `timestamp` | `behavior_type`: hand_up/standing/head_down/talking。关联 task_id |

**Device** 由边侧**内存维护**（在线状态 + 最后心跳时间），不持久化。重启后靠端侧上线宣告重建。

### 3.7 任务请求消息格式

端侧构造 Task 后发布到 `edge/task/request/{device_id}`（QoS 1）：

```json
{
  "task_id": "uuid-or-snowflake",
  "task_type": "face_attendance",
  "trigger_source": "user_button",
  "session_id": "classroom-301_2026-05-26_08-00",
  "device_id": "classroom-301",
  "created_at": "2026-05-26T08:15:02.123",
  "image": "<base64 编码图像>",
  "params": {}
}
```

- `image`：face_attendance 附带人脸区域裁剪图，behavior_analyze 附带全帧。report_generate 无 image。
- `params`：扩展字段，当前为空。预留用于"高精度模式"等可选参数。
- person_count **不发布** Task 请求到 MQTT，仅通过 `edge/status/person_count/{device_id}` 上报计数结果。

## 4. 课堂生命周期

### 4.1 课表驱动

系统严格按课表运行。课表为 Atlas 上 JSON 配置文件，格式如下：

```json
{
  "schedule": [
    {
      "day_of_week": 1,
      "start_time": "08:00",
      "end_time": "08:45",
      "course_name": "数学",
      "teacher": "张老师",
      "class_name": "三年二班",
      "device_id": "classroom-301"
    }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `day_of_week` | 1=周一 … 7=周日 |
| `start_time` / `end_time` | 上课/下课时间 |
| `device_id` | 必填，绑定到具体端侧设备（为多端侧预留） |

### 4.2 Session 生命周期

```
上课时间到 → 自动创建 Session（session_id = {device_id}_{date}_{start_time}）
           → 写入 SQLite（status='active', ended_at=NULL）
           → 启动 person_count 定时执行
           → 教师可触发签到/行为分析（person_count 执行期间跳过）
           → 教师可多次触发签到（每次独立存储，以 task_id 区分）
           → 教师可中途触发报告（"中期报告"，Session 不结束）
下课时间到 → 更新 ended_at + status='completed'
           → 自动触发 report_generate（"最终报告"，Session 结束）
```

- 非上课时段：端侧只发心跳，不执行推理。课表无课则全天休眠。
- 临时调课：直接修改课表 JSON 文件，重启边侧服务生效。
- **背靠背课堂**（无课间间隔）：上一节 report_generate 与下一节 session 创建可**并行执行**，端侧切换新 session_id 继续 person_count。
- **边侧重启恢复**：通过 `SELECT * FROM sessions WHERE ended_at IS NULL` 识别活跃 session。

### 4.3 端侧并发控制

- 端侧同时只执行一个推理
- 维护 FIFO 任务队列（深度 1）
- person_count 优先完成当前帧，之后处理队列中的按键任务
- person_count 按时间间隔执行（与帧率解耦），间隔为可配置参数
- person_count 执行期间若有新按键任务到达 → 加入队列（深度 1）。队列满时新触发被丢弃，端侧 Web 提示"任务进行中，请稍后再试"
- person_count 执行期间若又到下一轮 person_count → 跳过（drop frame）

## 5. 三层协同

### 5.1 调度协同

调度引擎运行在边侧 Atlas，接收 MQTT 上的任务请求，按策略决策目标执行层。

**决策因素**：
- 任务需要的模型能力（端有无对应模型）
- 各层当前负载（队列深度、NPU/CPU 利用率）
- 端-边-云之间实时网络延迟
- 教师是否指定"高精度模式"（强制上浮）

**策略（可切换）**：

| 策略 | 逻辑 |
|---|---|
| 贪心就近 | 能端不边，能边不云 |
| 负载均衡 | 每层维护能力分数，选最空闲 |
| 自适应（默认） | 综合延迟(0.5) + 精度(0.3) + 负载(0.2) 加权打分 |

> **v1 调度范围**：`person_count` 端侧硬约束（透传），`face_attendance` 边侧硬约束（人脸库依赖），`report_generate` 云端硬约束（格式化能力）。仅 `behavior_analyze` 有边/云二选一的调度决策空间，三种策略的差异由此体现。
> 
> 对于 `person_count`，调度引擎透传——决策结果始终为端侧执行，不参与实际调度。

### 5.2 模型协同

| 层 | 硬件 | 推理框架 | 运行模型 | 推理能力 |
|---|---|---|---|---|---|
| 端 | Milk-V Duo256M | TDL SDK (C++) | YOLOv5n (.cvimodel) | 人体检测 + 人数统计 |
| 边 | Atlas 200I DK A2 | **MindX SDK mxVision** (Python) | RetinaFace + ArcFace / YOLOv5m + 规则引擎 (.om) | 人脸检测 + 特征提取 + 身份比对 / 行为分析 |
| 云 | PC | ONNX Runtime / OpenCV DNN | YOLOv5m + 规则引擎 / 报告格式化 | 人体检测 + 行为分析 + 报告格式化 |

- 三级模型通过统一任务接口接入
- 各层模型启动时预加载到内存，避免首次推理冷启动
- 边侧模型需经 ATC 工具转换为 .om 格式，通过 MindX SDK Pipeline/Model API 调用，DVPP 硬件加速预处理
- 首期云端行为分析使用**规则引擎降级**（人体检测 + 启发式规则判断举手/起立/低头/交谈），不强制深度学习行为分类模型
- **边侧也可执行 behavior_analyze**，使用与云端相同的 YOLOv5m + 规则引擎，保证调度策略对比的公平性

### 5.3 数据协同

| 场景 | 数据流向 | 说明 |
|---|---|---|
| 常态 person_count | 端→边（MQTT, QoS 0） | 结构化数据 `{count, timestamp}`，不传原图 |
| 签到模式 | 端→边（MQTT, QoS 1） | 传人脸区域裁剪图，相比全帧压缩 80%+ |
| 行为分析模式 | 端→边→云（MQTT, QoS 1） | 端侧经边侧中转全帧到云，教师主动触发，低频 |
| 行为分析模式（边侧执行） | 端→边（MQTT, QoS 1） | 调度引擎决策边侧执行时，全帧到达边侧即止 |
| 报告生成 | 边→云（MQTT, QoS 1） | 边侧聚合 SQLite 数据后附带在任务中发云端 |
| 断网离线 | 端侧本地缓存 | JSON 文件追加写入，恢复连接后批量同步，同步完删除 |

### 5.4 数据持久化

| 数据 | 存储位置 | 留存时长 |
|---|---|---|
| 签到记录（原始） | 边侧 SQLite | 一学期 |
| 行为分析结果（原始） | 边侧 SQLite | 一学期 |
| 人数统计 | 边侧 SQLite | 上课期间原始数据点，下课时聚合为每课摘要（avg/max/min/count），聚合留存一学期，原始点仅保留当天 |
| 性能指标 | 边侧内存 | 最近窗口（不长期存储） |
| 课堂报告文件 | 云端本地 | 边侧 HTTP 获取 |

- 边侧 SQLite 为主存储
- 云端仅做推理计算和报告文件存储，不存业务数据
- 端侧离线期间用 JSON 文件追加写入

### 5.5 人脸库管理

Atlas 本地目录结构：

```
/data/face_lib/
├── students.json              # 花名册（唯一数据源）
├── photos/                    # 学生照片
│   ├── 张三.jpg
│   └── 李四.jpg
└── embeddings/                # 预提取特征向量（持久化缓存）
    ├── 张三.npy
    └── 李四.npy
```

**students.json**：
```json
[
  {"student_id": "2024001", "name": "张三", "photo": "photos/张三.jpg"},
  {"student_id": "2024002", "name": "李四", "photo": "photos/李四.jpg"}
]
```

- 边侧启动时扫描目录、预提取特征向量，持久化到 `embeddings/` 为 `.npy` 文件
- 仅在 `photos/` 目录内容变化时重新提取
- 花名册为唯一数据源：`absent = 花名册全员 - present`，不在花名册中的为 `unknown`
- `student_id`（学号）必填——处理同名同姓情况
- 首期通过直接操作目录管理，不走 Dashboard 上传

## 6. 通信架构

### 6.1 MQTT Topic 完整目录

Broker（Mosquitto）部署在 Atlas 上。

#### 任务通路

| Topic | 方向 | QoS | 说明 |
|---|---|---|---|
| `edge/task/request/{device_id}` | 端→边 | 1 | 任务请求 |
| `edge/task/result/{device_id}` | 边/云→端 | 1 | 任务结果 |
| `cloud/task/request/{device_id}` | 边→云 | 1 | 路由到云的任务 |
| `cloud/task/result/{device_id}` | 云→端+边 | 1 | 云端执行结果（端侧展示，边侧写入 SQLite + 获取报告文件） |

#### 设备管理

| Topic | 方向 | QoS | 说明 |
|---|---|---|---|
| `edge/device/online/{device_id}` | 端→边 | 1 (retained) | 上线宣告 |
| `edge/device/offline/{device_id}` | 端→边 | 1 (retained) | 下线宣告（LWT 自动发布） |

#### 心跳与状态

| Topic | 方向 | QoS | 频率 |
|---|---|---|---|
| `edge/heartbeat/{device_id}` | 端→边 | 0 | 5s |
| `cloud/status/report` | 云→边 | 0 | 30s，含 cpu/gpu/memory/queue_depth/status，连续 2 次未收到（60s）判离线 |

#### 数据上报

| Topic | 方向 | QoS | 说明 |
|---|---|---|---|
| `edge/status/person_count/{device_id}` | 端→边 | 0 | 人数统计结果 |

#### 调度控制

| Topic | 方向 | QoS | 说明 |
|---|---|---|---|
| `edge/schedule/command/{device_id}` | 边→端 | 1 | 调度指令（策略切换通知、session 恢复指令等） |

> 调度引擎按 `task_id` 幂等去重（QoS 1 可能重复送达）。端侧设备异常断线时，Broker 通过 LWT（Last Will Testament）自动发布离线消息。

### 6.2 心跳格式

端侧每 5s 上报（QoS 0）：

```json
{
  "device_id": "classroom-301",
  "timestamp": "2026-05-26T08:15:02",
  "status": "online",
  "load": {
    "cpu_percent": 45.2,
    "npu_percent": 30.1,
    "memory_mb": 128
  },
  "task_queue_depth": 0,
  "bandwidth_bytes_sent": 1048576,
  "current_session_id": "classroom-301_2026-05-26_08-00",
  "current_policy": "adaptive"
}
```

- `bandwidth_bytes_sent` 为累计值，Dashboard 端做差值除时间窗得到速率
- `current_session_id` 为空时表示不在上课时段
- 边侧连续 3 次（15s）未收到心跳判定端侧离线

### 6.3 云端状态上报（MQTT）

云端每 30s 通过 MQTT `cloud/status/report` 上报负载（QoS 0）：

```json
{
  "cloud_id": "cloud-main",
  "timestamp": "2026-05-26T08:15:02",
  "load": {
    "cpu_percent": 55.0,
    "gpu_percent": 40.0,
    "memory_mb": 4096
  },
  "task_queue_depth": 0,
  "status": "online"
}
```

调度引擎连续 2 次未收到上报（60s）判定云端离线。

### 6.4 边→云 gRPC

边侧通过 gRPC 向云端上报状态（每 30s）：

```protobuf
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

### 6.5 Dashboard API（边侧 FastAPI + SSE）

```
GET /api/v1/nodes/status           # 三级节点在线状态 + CPU/NPU/队列
GET /api/v1/network/rtt            # 端-边、边-云 RTT
GET /api/v1/tasks/distribution     # 任务分配比例
GET /api/v1/tasks/timeline         # 最近 N 个任务时序
GET /api/v1/performance/latency    # 当前策略 CDF 数据
GET /api/v1/performance/throughput # 吞吐量
GET /api/v1/classroom/count-history # 人数变化数据点（活跃 session 返回原始点，历史 session 返回聚合摘要）
GET /api/v1/classroom/attendance    # 签到结果列表
GET /api/v1/classroom/behavior      # 行为分析摘要
```

- 实时数据通过 SSE 推送
- 策略对比 CDF 数据仅在实验模式各运行一轮后才有

### 6.6 端侧 Web API（Milk-V 极简 HTTP Server，端口 8080）

```
GET  /                        # Web 主页面（HTML）
GET  /api/status              # JSON: 人数、策略、网络状态、session
GET  /api/last_result          # JSON: 最近一次任务结果
GET  /api/screenshot           # 当前静态截图（JPEG）
POST /api/action/attendance    # 触发签到
POST /api/action/behavior      # 触发行为分析
POST /api/action/report        # 触发报告生成
POST /api/action/policy/{name} # 切换调度策略
```

- 端侧 HTTP Server 从本进程内存读取数据，浏览器不直连 MQTT
- 视频预览首期使用静态截图（定时刷新），手机浏览器兼容性最优

## 7. 端侧交互功能

端侧 = Milk-V Duo256M + 摄像头，使用 TDL SDK（C++）开发。

### 7.1 物理交互（GPIO 按键 / 命令行模拟）

**按键防抖**：500ms 防抖窗口，长按 2s 触发。

| 操作 | 触发行为 | 排队 |
|---|---|---|
| **按键 1 短按** | 切换调度策略（贪心 → 负载 → 自适应 → 贪心...） | 即时生效，不排队 |
| **按键 1 长按（2s）** | 强制切换为纯本地模式（紧急离线） | 即时生效，取消队列中所有任务 |
| **按键 2 短按** | 触发 `face_attendance` 签到任务 | 当前有任务执行中 → 加入队列（深度 1），队列满则丢弃 |
| **按键 2 长按（2s）** | 触发 `behavior_analyze` 课堂行为分析 | 同上 |
| **按键 3 短按** | 触发 `report_generate` 生成课堂报告 | 同上 |

**端侧并发控制**：同时只执行一个推理。维护 FIFO 任务队列（深度 1）。person_count 优先完成当前帧，之后处理队列中的按键任务。队列满时新触发被丢弃，端侧 Web 提示"任务进行中，请稍后再试"。

> 前期用命令行模拟按键输入，后续可迁移到 GPIO 物理按键。

### 7.2 本地 Web 界面（手机连 WiFi 访问 `http://milkv-ip:8080`）

- 当前人数显示（文字 + 定时刷新截图）
- 三个功能按钮：签到 / 课堂分析 / 生成报告
- 当前调度策略显示 + 切换下拉框
- 最近一次任务结果展示：
  - 签到：展示 present/absent/unknown 名单
  - 行为分析：展示行为统计摘要（举手 N 人/起立 N 人/低头 N 人/交谈 N 人）
  - 报告生成：展示"报告已生成"状态 + 关键摘要数字（应到/实到/缺席），完整报告在 Dashboard 查看
- 错误提示：边侧不可用时显示"本地服务器不可用，请联系管理员检查本地服务器"；云端不可用时显示"云端服务不可用"；任务进行中显示"任务进行中，请稍后再试"

### 7.3 端侧本地显示（可选）

若有显示外设，OSD 叠加显示当前人数、策略标识、网络状态。

## 8. Dashboard 功能（管理员，PC 浏览器）

### 8.1 系统监控面板

- 三级节点在线状态（绿/黄/红，端侧心跳 15s 超时判定离线）
- 每层 CPU/NPU 利用率实时仪表盘
- 每层任务队列深度
- 端-边、边-云之间实时 RTT

### 8.2 任务调度视图

- 实时饼图：任务在三层间的分配比例
- 按任务类型分组柱状图
- 任务流转时序图（最近 N 个任务的执行路径、状态、延迟）

### 8.3 性能对比面板

- 三种调度策略的延迟 CDF 曲线（同一图，实验模式获取）
- 吞吐量对比柱状图
- 各层平均负载对比
- 日常只展示当前策略指标

### 8.4 课堂数据面板

- 当前课堂人数变化曲线
- 签到结果列表（姓名 + 时间 + present/absent/unknown）
- 行为分析结果摘要

### 8.5 视频预览

- 端侧最新静态截图（定时刷新）
- 首期不做实时视频流，后续可扩展 WebRTC

## 9. 性能指标

| 指标 | 定义 | 采集点 | 上报路径 |
|---|---|---|---|
| **端到端延迟** | `T_result - T_created` | 端侧打创建时间戳，结果回来时计算 | 随 Task 结果携带 |
| **各层推理延迟** | 模型 inference 前后时间差 | 各层 inference 函数内计时 | 随执行结果上报 |
| **调度延迟** | `T_assign - T_request_arrive` | 调度引擎内计时 | 引擎内部记录 |
| **系统吞吐量** | 每秒成功完成的任务数 | 调度引擎统一统计 | 内存累计 |
| **模型精度** | 各层模型测试集 mAP / 准确率 | 离线评测脚本 | 首期在系统中运行 |
| **带宽占用** | 端→边上行字节速率 | MQTT 消息体大小累计 | 端侧心跳附带（累计值） |
| **各层负载** | NPU/CPU 利用率均值 + 峰值 | 各层采集 | 端→心跳(5s)；边→本地；云→gRPC(30s) |
| **签到准确率** | 正确识别数 / 实际人数 | 离线评测脚本 | 首期在系统中运行 |
| **调度命中率** | 自适应策略选的最优层与事后最优层一致的比例 | 离线分析 | 首期在系统中运行 |

## 10. 运行模式

| 模式 | 触发条件 | 系统行为 |
|---|---|---|
| **正常** | 全链路正常 | 调度引擎在线，按课表自动运行 |
| **降级** | 边侧宕机（心跳 15s 超时） | 端侧退化为纯本地模式（仅 person_count），定时重连；face_attendance/behavior_analyze/report_generate → REJECTED |
| **离线** | 端侧断网（Broker 连接断开） | person_count 本地执行 + JSON 文件追加缓存，恢复后批量同步。交互式任务（face_attendance/behavior_analyze/report_generate）直接拒绝并提示"当前离线，无法执行此操作" |
| **云端不可用** | 云端 60s 无 MQTT 上报 | report_generate 直接 REJECTED（云独有能力）。behavior_analyze 调度引擎自动路由到边侧执行。端侧 Web 提示云端服务不可用 |
| **实验** | 管理员在 Dashboard 触发 | 边侧内置 benchmark 依次以三种策略发送模拟任务（预录测试图像），不阻塞真实任务，结果分开统计 |

## 11. 系统启动与恢复

### 11.1 启动顺序

```
1. Atlas: Mosquitto Broker 启动
2. Atlas: 边侧服务启动（模型预加载 + 人脸库预提取 + 课表加载 + 调度引擎）
3. PC:   云端服务启动（模型预加载 + 连 Broker + 启动 gRPC 接收边侧上报）
4. Milk-V: 端侧服务启动（连 Broker + 发上线宣告 + 等课表时间到）
```

### 11.2 重启恢复

| 场景 | 行为 |
|---|---|
| 仅端侧重启 | 上线宣告后，边侧识别活跃 session（`ended_at IS NULL`）→ 下发恢复指令（session_id + 策略）→ 端侧从当前时刻恢复 person_count，不补算丢失时段，历史签到/行为数据不受影响 |
| 仅边侧重启 | 扫描 SQLite 活跃 session（`ended_at IS NULL`）→ 恢复课表监听。进行中任务超时 FAILED，教师重试 |
| Broker+边侧都重启 | QoS 1 消息可能丢失，教师按键无响应时重试 |
| 端侧课堂中途接入 | 边侧识别活跃 session → 下发恢复指令 → 端侧直接开始 person_count，即使只剩几分钟也正常执行 |

## 12. 设备标识

端侧 `device_id` 采用静态配置，启动时直接使用预置值。架构上不硬编码单节点，MQTT topic 和调度引擎均支持多端侧，按 `device_id` 区分。首期单端侧验证功能。

## 13. 节点配置

每个节点一个 YAML 配置文件：

```yaml
# 端侧配置示例 (milkv_config.yaml)
device_id: "classroom-301"
mqtt:
  broker_host: "192.168.1.100"
  broker_port: 1883
person_count:
  interval_seconds: 2
web_server:
  port: 8080
camera:
  device: "/dev/video0"
  screenshot_interval_seconds: 1

# 边侧配置示例 (edge_config.yaml)
mqtt:
  broker_host: "localhost"
  broker_port: 1883
scheduler:
  timeout_person_count_ms: 3000
  timeout_face_attendance_ms: 15000
  timeout_behavior_analyze_ms: 30000
  timeout_report_generate_ms: 30000
api:
  fastapi_port: 8000
grpc:
  listen_port: 50051
paths:
  face_lib: "/data/face_lib"
  schedule: "/data/schedule.json"
  sqlite_db: "/data/edge.db"
  models: "/data/models"

# 云端配置示例 (cloud_config.yaml)
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
http:
  host: "0.0.0.0"
  port: 8081
```

## 14. 技术选型

| 组件 | 运行位置 | 技术 |
|---|---|---|
| 端侧推理 + HTTP Server | Milk-V Duo256M | TDL SDK (C++) |
| **边侧推理** | **Atlas 200I DK A2** | **MindX SDK mxVision** (Python 3.9) |
| 调度引擎 | Atlas 200I DK A2 | Python asyncio |
| 边侧 API | Atlas 200I DK A2 | Python FastAPI + SSE |
| MQTT Broker | Atlas 200I DK A2 | Mosquitto |
| 边→云通信 | Atlas → PC | gRPC Python |
| 云端推理 + 报告 | PC | Python + ONNX Runtime / OpenCV |
| Dashboard 前端 | PC 浏览器 | 纯 HTML + Vanilla JS + Chart.js |

> **边侧推理选型说明**：选用 MindX SDK mxVision 而非直接封装 PyACL/CANN。mxVision 提供 Pipeline 插件化编排和 Model API 两种模式，内置 DVPP 硬件加速预处理、NMS 后处理等插件，大幅减少样板代码，且由华为官方保证与 Ascend 310P 的适配优化。Python 3.9 为 MindX SDK 硬性版本要求。

## 15. 多端侧扩展预留

- MQTT topic 设计包含 `device_id` 维度
- 调度引擎支持多端侧能力注册，按 `device_id` 区分
- Dashboard 支持按端侧节点筛选视图
- 课表 `device_id` 字段必填，天然支持多教室
- 首期单端侧验证功能，架构上不排斥后续增加节点
