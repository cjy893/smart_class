# PRD: 端侧设备程序 (edge_compute_device)

## Problem Statement

智慧课堂系统需要在 Milk-V Duo256M 端侧设备上运行一个完整的推理+通信程序，实现人数统计（YOLOv5n）、任务收发（MQTT）、按键交互（GPIO）、Web 管理界面（HTTP），以及与边侧/云端的协同通信。该程序需要集成到算能 TDL SDK 的交叉编译工具链中，在 RISC-V musl 平台上正确构建和部署。

## Solution

在 TDL SDK 的 `sample/edge_compute_device/` 下开发一个多模块 C++ 应用程序（~2200 行），使用 SDK 内置的 CVI_TDL API 进行 NPU 推理，通过 paho.mqtt.c 和 libmicrohttpd 两个第三方库实现 MQTT 通信和 HTTP 服务，按课表驱动全自动运行。

## User Stories

1. 作为教师，我希望能通过 Milk-V 上的物理按键触发签到、行为分析和课堂报告，以便在课堂上无需电脑即可操作
2. 作为教师，我希望能通过手机 WiFi 访问 Milk-V 的 Web 页面查看当前人数、摄像头截图和最近任务结果，以便在教室内移动时也能掌握课堂状态
3. 作为教师，我希望按键有 500ms 防抖保护，长按 2s 触发不同功能，避免误操作
4. 作为系统管理员，我希望端侧设备启动后自动连接 MQTT Broker 并发布上线宣告，无需手动配置
5. 作为系统管理员，我希望端侧在断网时自动缓存 person_count 数据到本地 JSON 文件，恢复后批量同步
6. 作为系统管理员，我希望端侧心跳每 5s 上报设备 CPU/NPU/内存/队列深度，边侧 15s 未收到判定离线
7. 作为系统，person_count 应按可配置的时间间隔（默认 2s）在本地 NPU 上执行 YOLOv5n 推理，不经过 MQTT 调度
8. 作为系统，端侧应维护一个 FIFO 深度为 1 的任务队列，person_count 优先于按键任务，队列满时丢弃并提示
9. 作为系统，端侧在收到边侧 session 恢复指令后应恢复 person_count，不补算丢失时段
10. 作为系统，端侧应支持按键 1 短按循环切换调度策略、长按强制本地模式

## Implementation Decisions

### 1. 模块架构

端侧程序由 10 个模块组成，由 App 主控编排：

| 模块 | 职责 | 接口 |
|---|---|---|
| App | 主控循环 + 状态机 + 模块编排 | `init(config_path)`, `run()`, `shutdown()` |
| Config | 配置加载（key=value 格式，无外部依赖） | `DeviceConfig load_config(path)` |
| TaskQueue | FIFO 任务队列（深度 1，线程安全） | `push() → bool`, `pop() → bool`, `stop()` |
| InferenceEngine | TDL SDK YOLOv5n 封装 | `init(model, threshold, nms)`, `detect_persons(rgb, w, h) → int` |
| MqttClient | paho.mqtt.c 封装 | `connect()`, `publish()`, `subscribe()`, LWT 自动设置 |
| HttpServer | libmicrohttpd 封装 | `start(port)`, REST API: `/api/status`, `/api/last_result`, `/api/screenshot`, `/api/action/*` |
| GpioHandler | 按键处理（500ms 防抖，2s 长按） | `init(debounce_ms, long_press_ms)`, `on_event(cb)`, 支持 GPIO/CLI 双模式 |
| Camera | V4L2 摄像头采集 | `open(device, w, h)`, `capture_rgb()`, `capture_jpeg()` |
| OfflineCache | 离线 JSONL 文件缓存 | `append(json)`, `read_all()`, `clear()` |
| Heartbeat | 5s 定时心跳上报 | `init(mqtt, device_id, interval)`, `start()`, `stop()` |

### 2. 状态机

```
INIT → CONNECTING → ONLINE → ACTIVE(session中) / IDLE(非上课)
ACTIVE → DEGRADED(边侧离线) → ACTIVE(边侧恢复)
ANY → OFFLINE(断网, person_count本地+缓存)
```

### 3. MQTT Topic 交互

端侧发布：
- `edge/device/online/{device_id}` — QoS 1, retained（上线宣告）
- `edge/heartbeat/{device_id}` — QoS 0, 5s（心跳）
- `edge/status/person_count/{device_id}` — QoS 0（人数结果）
- `edge/task/request/{device_id}` — QoS 1（face_attendance / behavior_analyze / report_generate 任务请求）

端侧订阅：
- `edge/task/result/{device_id}` — QoS 1（边侧/云端执行结果）
- `cloud/task/result/{device_id}` — QoS 1（云端执行结果）
- `edge/schedule/command/{device_id}` — QoS 1（调度指令：session 恢复、策略变更）

LWT: Broker 在端侧异常断线时自动发布 `edge/device/offline/{device_id}`

### 4. TDL SDK 集成

- 使用 `CVI_TDL_Detection` + `CVI_TDL_SUPPORTED_MODEL_YOLOV5` 进行人体检测
- 模型加载使用 `CVI_TDL_OpenModel`，阈值通过 `CVI_TDL_SetModelThreshold` 配置
- 计数逻辑：遍历 `cvtdl_object_t.info[]`，筛选 `classes == 0`（COCO person 类）
- 推理耗时通过 `std::chrono` 在检测前后计时

### 5. 第三方库集成

两个库通过 FetchContent 从预编译 tarball 导入：

| 库 | 用途 | cmake 文件 | tarball 位置 |
|---|---|---|---|
| paho.mqtt.c | MQTT 异步客户端 | `cmake/paho_mqtt.cmake` | `oss/oss_release_tarball/{ARCH}/paho_mqtt.tar.gz` |
| libmicrohttpd | 嵌入式 HTTP 服务器 | `cmake/microhttpd.cmake` | `oss/oss_release_tarball/{ARCH}/libmicrohttpd.tar.gz` |

Tarball 结构要求：`include/*.h` + `lib/*.so*`

构建时自动设置 `PAHO_MQTT_FOUND` / `MICROHTTPD_FOUND`，库不存在时 `FATAL_ERROR`。

### 6. 编译平台适配

- C++ 标准：`gnu++11`（与 TDL SDK 一致）
- 禁用 C++14 特性（`std::make_unique` → `std::unique_ptr<T>(new T(...))`）
- TDL SDK 头文件不包裹 `extern "C"`（内部已处理 C/C++ 链接，且含 C++ 重载）
- 配置文件解析使用自实现 key=value 解析器（无 yaml-cpp）

### 7. 运行时依赖

| 依赖 | 类型 | 部署方式 |
|---|---|---|
| `libcvi_tdl.so` 等 | 动态库 | 开发板固件自带 |
| `libpaho-mqtt3a.so` | 动态库 | 随 tarball 解压，install 到 `/mnt/system/lib/` |
| `libmicrohttpd.so` | 动态库 | 同上 |
| `yolov5n.cvimodel` | 模型文件 | 部署到 `/data/models/` |

### 8. GPIO 按键映射

| 操作 | Event | 行为 |
|---|---|---|
| 按键 1 短按 | `BTN_1_SHORT` | 循环切换策略（贪心→负载→自适应） |
| 按键 1 长按 2s | `BTN_1_LONG` | 强制本地模式，清空任务队列 |
| 按键 2 短按 | `BTN_2_SHORT` | 触发 face_attendance |
| 按键 2 长按 2s | `BTN_2_LONG` | 触发 behavior_analyze |
| 按键 3 短按 | `BTN_3_SHORT` | 触发 report_generate |

### 9. Web API

```
GET  /api/status           → {person_count, policy, network_status, session_id, error}
GET  /api/last_result      → 最近一次任务结果 JSON
GET  /api/screenshot       → JPEG 静态截图
POST /api/action/attendance → 触发签到
POST /api/action/behavior   → 触发行为分析
POST /api/action/report     → 触发报告生成
POST /api/action/policy/{name} → 切换策略
```

## Out of Scope

- 端侧的人脸检测/识别（由边侧 Atlas 完成）
- 端侧的行为分析（由边侧或云端完成）
- Dashboard 管理界面（由边侧 FastAPI + 前端完成）
- 实验模式 benchmark 工具（边侧功能）
- GPIO 物理引脚的实际驱动（当前用 CLI 模拟模式）
- person_count 离线缓存的自动清理策略（当前仅按课粒度聚合）

## Further Notes

- 端侧原始代码也存在于 `/mnt/e/edge_compute/device/` 目录中，该版本使用 `#ifdef MILKV_PLATFORM` 双平台编译（PC stub + Milk-V 真实），适合独立开发和测试
- TDL SDK 集成版本（`tdl_sdk/sample/edge_compute_device/`）去掉了双平台条件编译，直接使用真实 TDL API
- 首次完整构建使用 `build_all`，后续修改端侧代码后只需 `clean_tdl_sdk && build_tdl_sdk`
