# 端侧代码待完成项

## 已确认可工作

- MMF 管线 (VI+ISP+VPSS) 初始化与清理
- YOLOv8n 模型加载与 person_count 推理
- MQTT raw socket 实现（去除 paho.mqtt.c 依赖，避免 musl 线程兼容性问题）
- MQTT 全部 topic 收发（8 个 topic，含 LWT，QoS 0/1）
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

---

## 待完成项

### P0 — 阻塞端到端链路

#### 1. 任务请求图像是假数据

**文件**: `app.cpp:trigger_face_attendance()`, `trigger_behavior_analyze()`

当前代码发送 `{"w":768,"h":432}` 元数据 JSON，非真实图片。边侧推理收不到有效图像，签到/行为分析无法工作。

**修复**: 从 VPSS 帧提取图像数据并做 base64 编码。短期可用软件 JPEG 编码（stb_image_write 或 libjpeg-turbo），长期用 IVE 硬件编码。

---

#### 2. GPIO 按键未启动

**文件**: `app.cpp:init_modules()`

`gpio_->start()` 从未被调用。物理按键完全不工作（Web UI 按钮可暂代）。

**修复**: 在 `init_modules()` 末尾添加 `gpio_->start()`。

---

### P1 — 核心功能完善

#### 3. 截图是 JPEG（非 JSON）

**文件**: `app.cpp:capture_screenshot_jpeg()`

Web UI `<img src="/api/screenshot">` 收到 `{"width":768,"height":432}` 而非 JPEG 二进制。影响端侧 Web 实时画面显示。

**修复**: VPSS 帧 → JPEG 编码。

---

#### 4. Edge 离线检测未实现

**文件**: `app.cpp:run()`

`on_edge_offline()` / `on_edge_online()` 已定义但无触发机制。边侧断连时端侧不会自动降级。

**修复**: 订阅 `edge/device/offline/{edge_id}` LWT topic，收到后进入 DEGRADED。

---

### P2 — 精度与细节

| # | 项 | 说明 |
|---|---|---|
| 5 | 心跳负载值硬编码 | CPU 45.0 / NPU 30.0 / 内存 128 写死，需读 `/proc/stat`、`/proc/meminfo` |
| 6 | 心跳 status 字段 | 硬编码 `"online"`，DEGRADED 状态时仍报 online |
| 7 | GET / 不返回 Web 页面 | 返回 `"text/html placeholder"` 而非 `web/index.html` |

---

## 低优先级

| 项 | 说明 |
|---|---|
| OSD 本地显示 | 需求 7.3 标注为"可选"，未实现 |
| `publish_task_request` 未检查返回值 | MQTT send 失败时静默丢弃 |
| 状态机转换无合法性校验 | 理论上可从任意状态跳到任意状态 |
| Web 无云端离线提示 | 需求 7.2 要求显示"云端服务不可用" |
