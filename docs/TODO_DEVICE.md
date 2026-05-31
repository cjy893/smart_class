# 端侧代码待完成项

> 基于 2026-06-04 更新。实际代码路径 `tdl_sdk/sample/edge_compute_device/`。

## 已确认可工作

- MMF 管线 (VI+ISP+VPSS) 初始化与清理
- YOLOv8n 模型加载与 person_count 推理
- MQTT raw socket 实现（去除 paho.mqtt.c 依赖，避免 musl 线程兼容性问题）
- MQTT 全部 topic 收发（9 个 topic，含 LWT + edge offline，QoS 0/1）
- MQTT 断连降级（进入 OFFLINE 状态，person_count 本地缓存）
- MQTT 非阻塞 init（连接失败不退出，进入 OFFLINE，HTTP 照常启动）
- MQTT 自动重连（run() 主循环 5s 间隔后台重试，重连成功 flush 离线缓存 + 重订阅）
- 任务队列（FIFO 深度 1，person_count drop frame）
- Session 恢复指令解析与执行
- HTTP API 全部 7 个端点
- Web UI 页面结构与自动刷新
- 策略切换 (BTN_1_SHORT) 与强制本地模式 (BTN_1_LONG)
- 状态机全部 6 个状态及转换日志
- Ctrl+C 信号处理与干净退出（无 segfault，MMF 资源正确释放）
- Milk-V ↔ Atlas USB RNDIS 网络（静态 IP + 持久化 ARP + mosquitto 匿名访问）
- JPEG 编码 + base64（OpenCV cv::imencode，参照 cvi_kit CVI_TDL_SavePicture 模式）
- Edge 离线检测 + DEGRADED 降级
- GPIO 按键启动 + 无硬件时的 30s 定时模拟测试
- 开机自启动 (device/src/auto.sh → /mnt/data/auto.sh, S99user 自动调用)

---

## 已修复

### P0-1. 任务请求图像是假数据 ✓

**文件**: `app.cpp`

**修复内容**:
- 新增 `encode_frame_to_jpeg()` — CVI_SYS_Mmap → cv::merge BGR planar → cv::imencode 内存 JPEG
- 新增 `base64_encode()` — 标准 base64 编码器
- `trigger_face_attendance()` 和 `trigger_behavior_analyze()` 改为真实 JPEG + base64

### P0-2. GPIO 按键未启动 ✓

**文件**: `app.cpp:init_modules()`

**修复内容**:
- 在 `init_modules()` 末尾添加 `gpio_->start()`

### P0-3. Edge 离线检测未实现 ✓

**文件**: `app.cpp:setup_mqtt_subscriptions()`

**修复内容**:
- 新增订阅 `edge/device/offline/{device_id}` (QoS 1)，收到后触发 `on_edge_offline()` → DEGRADED 降级

### P1-3. 截图是 JSON 非 JPEG ✓

**文件**: `app.cpp:capture_screenshot_jpeg()`

**修复内容**:
- 改为调用 `encode_frame_to_jpeg()`，与 P0-1 共用同一 JPEG 编码方案

---

## P2 — 精度与细节

| # | 项 | 代码位置 | 说明 |
|---|---|---|---|
| 5 | 心跳负载值硬编码 | `app.cpp:75-77` lambda 返回 `45.0, 30.0, 128` | 需读 `/proc/stat`、`/proc/meminfo` |
| 6 | 心跳 status 硬编码 | `heartbeat.cpp:86` 写死 `"online"` | DEGRADED 时仍报 online |
| 7 | GET / 不返回 Web 页面 | `http_server.cpp:145` 返回 `"text/html placeholder"` | 需读 `web/index.html` 文件并返回 |

---

## 低优先级

| 项 | 说明 |
|---|---|
| OSD 本地显示 | 需求 7.3 标注为"可选"，未实现 |
| `publish_task_request` 未检查返回值 | MQTT send 失败时静默丢弃 |
| 状态机转换无合法性校验 | 理论上可从任意状态跳到任意状态 |
| Web 无云端离线提示 | 需求 7.2 要求显示"云端服务不可用" |
