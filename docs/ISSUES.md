# 项目当前问题汇总

> 2026-06-01，端-边 MQTT 通信刚修通，端到端链路初具雏形。

## 已修复问题

| # | 问题 | 修复 |
|---|---|---|
| 1 | MQTT raw socket 剩余长度编码 bug（>=128 字节时覆盖 topic） | 重构 publish/subscribe：先算 RL 再写数据 |
| 2 | MQTT recv header 解析 bug（控制字节被当剩余长度，全 0） | 分离控制字节和剩余长度读取 |
| 3 | recv 线程从未启动（`start_loop()` 未调） | `connect()` 内自动调用 |
| 4 | 重连后 recv 线程不重启（`recv_running_` 未清零） | `connect()` 开头调 `stop_loop()` |
| 5 | QoS 1 PUBLISH 缺 Packet ID（payload 前 2 字节被吞） | 加 2-byte packet identifier |
| 6 | 边缘 schedule 重启不触发上课回调 | `_init_active_sessions` 调用 `on_class_start` |
| 7 | Session 已存在时不重发 session_restore | 发现已有 session 时仍 publish |
| 8 | 课表下课回调为空 | 接入 `session_mgr.end_session()` + 触发 report_generate |
| 9 | LWT offline 未订阅 | 补齐 `edge/device/offline/#` 订阅 |
| 10 | report_generate 聚合数据未接入 dispatch | cloud 分支改为 `_build_cloud_request()` |
| 11 | gRPC 客户端空壳 | 实现 StatusReport + Heartbeat RPC（需云端 server 在线） |
| 12 | person_count 硬约束路由错误 | 移除调度引擎，只做数据入库 |

---

## 当前开放问题

### P0 — 阻塞端到端

#### 1. 端侧 task 请求不带图像数据

**现象**：边侧收到 task 请求但 `_task_images` 为空，日志 `No image data for task ...`。

**分析**：端侧 `trigger_face_attendance()` 和 `trigger_behavior_analyze()` 构造 MQTT 消息时，`image` 字段为空字符串或未编码。需要确认：
- `encode_frame_to_jpeg()` 是否正确从 VPSS buffer 抓帧 → JPEG 编码
- `base64_encode()` 是否正确编码到 JSON 的 `"image"` 字段
- VPSS 抓帧失败时是否有 fallback 或明确的错误上报

**解决方向**：
- 检查端侧 task 发送日志，确认 image 字段长度
- VPSS Grp 1 当前有 buffer 分配失败（见问题 2），可能导致抓帧失败
- 如 frame 不可用，可先用测试 JPEG（已知文件）验证边侧推理链路

#### 2. 端侧 VPSS 视频管线 buffer 不足

**现象**：

```
required size(1228800) > pool(2)'s blk-size(995328)
Grp(1) Chn(0) Can't acquire VB BLK for VPSS
```

**分析**：VPSS Grp 1 的 pool 2 太小（995KB），不足以分配 1228800 字节 buffer。
Grp 0 Chn 0 (768x432) 使用 pool 2 (995328)，Grp 1 Chn 0 (1280x720) 需要 >1.2MB 但 pool 不够大。

**解决方向**：
- 增大 VBPool 2 的 size（`mmf_pipeline.cpp` 中的 pool 分配）
- 或调整 Grp 1 的输出分辨率以匹配现有 pool
- 或重排 Grp/Chn 分配，让 1280x720 用更大的 pool

---

### P1 — 核心功能

#### 3. 边侧推理链路未端到端验证

**现象**：从 MQTT 收 task → scheduler 调度 → `_execute_local` → FaceEngine/BehaviorEngine 推理这条链路的完整测试未做。

**分析**：三个模型单独测试已 PASS（`test_models.py`），但从 MQTT 消息到最终结果的集成链路因缺图像数据未能验证。

**解决方向**：
- 用 `mosquitto_pub` 发一条带 base64 测试图像的 task，验证边侧完整推理链路
- 验证 face_attendance 流程：检测 → 特征提取 → 人脸库匹配 → 签到记录入库
- 验证 behavior_analyze 流程：人体检测 → NMS → 规则引擎 → 行为记录入库

#### 4. 云端服务未启动

**现象**：gRPC Connection refused，没有云端 gRPC server 在运行。

**分析**：云端代码（`cloud/` 目录）有完整实现和测试用例，但未部署到 PC 运行。边→云 MQTT task 转发和 gRPC status report 均无法到达。

**解决方向**：
- 在 PC (192.168.137.1) 上启动云端 service
- 或先通过 MQTT fallback 验证云端通信（`cloud/task/request/#` topic）

#### 5. 人脸库缺照片

**现象**：`Photo not found: .../李四.jpg`，1/2 学生缺照片。

**解决方向**：补齐 photos/ 目录下的学生照片文件。

---

### P2 — 完善

| # | 问题 | 说明 |
|---|---|---|
| 6 | gRPC fork/epoll 兼容 | uvicorn fork 与 gRPC 线程冲突，报 `fork_posix.cc` / `ev_epoll1_linux.cc` 警告。不影响功能但日志噪音大。可禁用 gRPC 直到云端就绪 |
| 7 | Experiment 模块未接入 | `experiment.py` 完整但未接入 `main.py` + `routes.py` |
| 8 | 端侧心跳负载值硬编码 | CPU/NPU/Memory 为固定值，未读 `/proc` |
| 9 | VPSS Grp 0 Chn 0 分辨率 768x432 | YOLOv8n 输入 640x640，存在不必要缩放 |
| 10 | MindX SDK set_env.sh not found | Warning，PATH 已手动配好，不影响功能但日志有噪音 |

---

## 端到端链路当前状态

```
端侧 Milk-V               边侧 Atlas              云端 PC
────────────────────────────────────────────────────────────
摄像头 ✓                  MQTT Broker ✓
YOLOv8n ✓                 MindX SDK ✓
JPEG 编码 ?               模型预加载 ✓
MQTT pub ✓ (已修复)       调度引擎 ✓              MQTT 订阅 ✓
task 请求 ✓ (缺图)        task 接收 ✓             gRPC server ✗
person_count ✗ (VPSS)     推理执行 ✗ (缺图)       推理未部署
session_restore 收 ✓      DB 存储 ✓
                           API/SSE ✓
```
