# 端侧代码待完成项

## 已确认可工作

- MMF 管线 (VI+ISP+VPSS) 初始化与清理
- YOLOv8n 模型加载与 person_count 推理
- MQTT 全部 topic 收发（8 个 topic，含 LWT）
- MQTT 断连降级（进入 OFFLINE 状态，persist_count 本地缓存）
- MQTT 自动重连（5s 间隔，flush 离线缓存，重订阅）
- 任务队列（FIFO 深度 1，person_count drop frame）
- Session 恢复指令解析与执行
- HTTP API 全部 7 个端点
- Web UI 页面结构与自动刷新
- 策略切换 (BTN_1_SHORT) 与强制本地模式 (BTN_1_LONG)
- 状态机全部 6 个状态及转换日志
- Ctrl+C 信号处理与干净退出

---

## 待完成项

### 1. GPIO 按键未启动

**文件**: `app.cpp:init_modules()`

`gpio_->start()` 从未被调用。`GpioHandler` 已初始化并注册回调，但轮询线程未启动，物理按键完全不工作。

**修复**: 在 `init_modules()` 末尾添加 `gpio_->start()`。

---

### 2. 任务请求图像是假数据

**文件**: `app.cpp:trigger_face_attendance()`, `trigger_behavior_analyze()`

需求要求签到任务附带人脸裁剪图（base64），行为分析附带全帧（base64）。当前代码发送的是 `{"w":768,"h":432}` 元数据 JSON。

**修复**: 从 VPSS 帧中提取图像数据并做 base64 编码（可用 TDL SDK 的 IVE 模块或软件编码）。若短期无法实现，至少需要标注此限制。

---

### 3. 截图是 JSON 元数据而非 JPEG

**文件**: `app.cpp:capture_screenshot_jpeg()`

Web UI 用 `<img>` 标签请求 `/api/screenshot`，但收到的是 `{"width":768,"height":432}` 而非 JPEG 二进制。

**修复**: 从 VPSS 帧生成 JPEG（IVE JPEG encoder 或 stb_image_write）。

---

### 4. 心跳负载值硬编码

**文件**: `app.cpp:init_modules()` → `heartbeat_->on_load_query(...)`

CPU 45.0、NPU 30.0、内存 128 是写死的常量，不是真实系统负载。

**修复**: 读取 `/proc/stat` 计算 CPU 使用率，读取 `/sys/class/npu/` 或相关接口获取 NPU 负载，读取 `/proc/meminfo` 获取内存使用。

---

### 5. 心跳 status 字段未反映离线/降级

**文件**: `heartbeat.cpp:build_heartbeat_json()`

`"status":"online"` 是硬编码。当端侧进入 OFFLINE 或 DEGRADED 状态时心跳仍报 online。注意：心跳本身在离线时无法送达（MQTT 断连），但 DEGRADED 状态下仍可送达。

**修复**: 心跳接收 App 状态或提供 `set_status()` 接口，在 DEGRADED 时报 `"degraded"`。

---

### 6. Edge 离线检测未实现

**文件**: `app.cpp:run()`

`on_edge_offline()` / `on_edge_online()` 已定义但无任何机制触发。需求规定边侧心跳 15s 超时判离线 → 端侧应退化为纯本地模式 (DEGRADED)。

**修复**: 端侧需订阅边侧状态或通过 MQTT 心跳超时检测（边侧断连时 MQTT Broker 发布 LWT 到 `edge/device/offline/{edge_id}`，端侧订阅此 topic 即可感知）。

---

### 7. GET / 不返回 Web 页面

**文件**: `http_server.cpp:handle_get()`

`GET /` 返回字符串 `"text/html placeholder"` 而非 `web/index.html` 的内容。

**修复**: 读取 `web/index.html` 文件内容并通过 MHD 返回，或将 HTML 编译进二进制（嵌入式常用做法）。

---

## 低优先级

| 项 | 说明 |
|---|---|
| OSD 本地显示 | 需求 7.3 标注为"可选"，未实现 |
| `publish_task_request` 未检查返回值 | MQTT send 失败时静默丢弃 |
| 状态机转换无合法性校验 | 理论上可从任意状态跳到任意状态 |
| Web 无云端离线提示 | 需求 7.2 要求显示"云端服务不可用" |
