# 云边端协同推理系统 — 领域词汇表

## 核心概念

- **Task（任务）**：系统中统一的执行单元。所有推理请求（人数统计、签到、行为分析、报告生成）均为 Task，包含 `task_type`、`trigger_source`、`status` 等字段。
- **TaskType（任务类型）**：`person_count` | `face_attendance` | `behavior_analyze` | `report_generate`，按复杂度递増。
- **TriggerSource（触发来源）**：`system_timer`（系统定时自动）| `user_button`（教师按键）| `dashboard_manual`（管理员手动），决定任务由谁发起。
- **TaskStatus（任务状态）**：`CREATED` → `QUEUED` → `DISPATCHED` → `EXECUTING` → `COMPLETED`，含两个终态 `REJECTED`（无层可用）和 `FAILED`（执行失败/超时）。`person_count` 直接从 `CREATED` 跳到 `COMPLETED`，跳过中间状态。
- **Layer（执行层）**：端（Milk-V）| 边（Atlas）| 云（PC），每层有不同模型能力和硬件资源。
- **SchedulingEngine（调度引擎）**：运行在边侧 Atlas，接收任务请求，按策略决定目标执行层。
- **SchedulingPolicy（调度策略）**：贪心就近 | 负载均衡 | 自适应（默认），教师可在端侧切换。
- **Session（课堂记录）**：每节课对应一条 Session，`session_id = {device_id}_{date}_{start_time}`。上课创建（`status='active'`），下课更新（`status='completed'`, `ended_at`）。边侧重启时通过 `ended_at IS NULL` 识别活跃 session。
- **PersonCount（人数采样）**：person_count 任务的每次计数结果，关联 session_id，包含 count + timestamp。上课期间保留原始点，下课时聚合为 session 级摘要。
- **AttendanceRecord（签到记录）**：face_attendance 任务的识别结果，关联 session_id，逐学生记录 present/absent/unknown。
- **BehaviorRecord（行为记录）**：behavior_analyze 任务的分析结果，关联 session_id，按行为类型（举手/起立/低头/交谈）统计。
- **Device（端侧设备）**：以 device_id 标识，静态配置。边侧内存维护在线状态 + 最后心跳时间，不持久化。重启后靠上线宣告重建。

## 已确认决策

- **Task 模型统一**：person_count 和其他三个任务类型共用同一 Task 模型，调度引擎对其透传（结果始终为端侧执行）。person_count 端侧本地 CREATED→COMPLETED，不发布 Task 请求到 MQTT，仅通过 `edge/status/person_count/{device_id}` 上报计数结果。
- **task_id 生成**：由触发端（端侧）在构造 Task 时生成（UUID 或雪花 ID）。边侧调度引擎按 task_id 幂等去重，作为防御性措施。
- **超时处理**：推理超时直接标记 FAILED，不自动重试，由教师重新触发。
- **降级提示**：边侧不可用时，REJECTED 任务在端侧 Web 显示"本地服务器不可用，请联系管理员检查本地服务器"。
- **MQTT 通路**：Broker 部署在 Atlas。云端也连此 Broker。任务上云时边侧发布到 MQTT topic，云端执行完后将结果发布到 MQTT。边侧和端侧同时订阅云端结果 topic——端侧用于展示，边侧用于写入 SQLite 和获取报告文件。
- **边→云状态上报**：边侧通过 gRPC 主动向云端上报状态/指标数据，与任务通路分离。
- **Dashboard 数据源**：Dashboard 实时数据从边侧 HTTP API 获取，不直接订阅 MQTT。
- **端侧心跳**：独立 MQTT topic，与状态上报分离。
- **设备标识**：端侧 device_id 采用静态配置，启动时直接使用预置值，发上线宣告到 `edge/device/online/{device_id}`。
- **person_count 节律**：按时间间隔执行，与帧率解耦。间隔为可配置参数。任务执行期间 person_count 跳过（drop frame），不排队。
- **端侧并发**：端侧同时只执行一个推理。维护 FIFO 任务队列（深度 1）。person_count 优先完成当前帧，之后处理队列中的按键任务。队列满时新触发被丢弃，端侧 Web 提示"任务进行中，请稍后再试"。按键防抖 500ms，长按 2s 触发。策略切换和强制本地模式即时生效，不排队。
- **边侧并发**：边侧维护串行任务队列，逐个执行推理任务（首期保守，避免 NPU 资源竞争）。
- **人脸库管理**：Atlas 本地指定目录存放学生照片+姓名，边侧启动时扫描目录、预提取特征向量。首期不作 Dashboard 上传。
- **端侧 Web 数据通路**：端侧 HTTP Server 从本进程内存读取数据（本地推理结果 + MQTT 收到的边侧结果），前端通过轮询/SSE 获取。不走浏览器直连 MQTT。
- **实时画面**：首期使用静态截图（定时刷新），供端侧 Web 和 Dashboard 预览。端侧 Web 通过 `/api/screenshot` 获取 JPEG。后续可扩展 RTSP/WebRTC 实时视频流。
- **Dashboard 数据更新**：前端通过 SSE 获取边侧 API 推送的实时数据。
- **策略对比**：日常只展示当前策略指标。三种策略的 CDF 对比数据需在"实验模式"下各策略分别运行一轮后才有。
- **课堂报告**：边侧从 SQLite 聚合数据后附带在任务中发给云端，云端负责格式化输出（JSON + HTML）。报告文件存储在云端，边侧通过 HTTP 获取供 Dashboard 展示。端侧 Web 仅展示报告已生成状态 + 关键摘要数字。教师中途按键触发为"中期报告"（Session 不结束，person_count 继续），下课自动触发为"最终报告"（Session 结束）。报告包含课堂基本信息、签到结果（应到/实到/缺席）、人数变化曲线、行为统计摘要、异常行为摘要。
- **课堂 Session**：按课表定义上课/下课时间。上课时间到 → 自动创建 session 记录（`status='active'`, `ended_at=NULL`）+ 启动 person_count；下课时间到 → 更新 `ended_at` + `status='completed'` + 触发 report_generate。非上课时段系统休眠，不执行推理。边侧重启时通过 `ended_at IS NULL` 识别活跃 session。同一 session 内允许多次签到，每次独立存储（以 task_id 区分），报告取最新一次结果。背靠背课堂（无课间间隔）：上一节 report_generate 与下一节 session 创建可并行执行，端侧切换新 session_id 继续 person_count。
- **课表管理**：课表为首期 Atlas 上 JSON 配置文件，包含教室、星期、上课/下课时间、课程名、教师、班级等字段。暂不走 Dashboard 上传。
- **person_count 上报**：每次计数完成后，端侧立即发布 MQTT 消息到 `edge/status/person_count/{device_id}`，边侧订阅后写入 SQLite。上课期间保留原始数据点供实时曲线渲染；下课时聚合为每课摘要（avg/max/min/count），聚合摘要留存一学期，原始点仅保留当天。API 对活跃 session 返回原始点，对历史 session 返回聚合摘要。
- **性能指标管线**：端到端延迟随 Task 结果带回；推理延迟随执行结果上报；调度延迟引擎内部记录；吞吐量引擎内存累计；带宽占用端侧心跳附带；负载每 5 秒采集上报（端→心跳，边→本地，云→gRPC）；签到准确率和调度命中率为离线评测脚本，首期需在系统中运行。
- **任务请求路由**：所有任务请求（含 behavior_analyze 全帧图像）统一经边侧调度引擎中转，不设端→云直通 topic。调度引擎统一追踪全局任务视图，决策上云后转发到 `cloud/task/request/{device_id}`。
- **任务超时**：按全链路（T_created → T_result）计时，超时阈值按任务类型区分。
- **数据持久化**：边侧 SQLite 主存储，云端不存业务数据。端侧离线期间：person_count 本地执行 + JSON 文件追加缓存，重连后批量推边侧并删除本地文件；face_attendance / behavior_analyze / report_generate 等交互式任务直接拒绝并提示"当前离线，无法执行此操作"。
  - 签到记录（原始）→ 留存一学期
  - 行为分析结果（原始）→ 留存一学期
  - 人数统计 → 上课期间原始点，下课时聚合为每课摘要（avg/max/min/count），聚合留存一学期，原始点仅保留当天
  - 性能指标 → 边侧内存保留最近窗口，不长期存储
- **云端不可用**：云端每 30s 通过 MQTT `cloud/status/report` 上报负载（cpu/gpu/memory/queue_depth/status）。调度引擎连续 2 次未收到上报（60s）判定云端离线。离线后 report_generate 直接 REJECTED（云独有能力），behavior_analyze 调度引擎自动路由到边侧。端侧 Web 提示云端服务不可用。
- **行为分析降级**：首期采用架构降级——行为分析使用规则引擎（人体检测 + 启发式规则判断举手/起立/低头/交谈）。边侧和云端均可执行 behavior_analyze，使用相同模型（YOLOv5m + 规则引擎），保证调度策略对比的公平性。调度引擎按策略在边/云之间决策。
- **MQTT QoS**：任务请求和结果 QoS 1（至少一次），调度引擎按 task_id 幂等去重；person_count 上报和心跳 QoS 0；端侧上线宣告 QoS 1 + retained。
- **启动顺序**：Broker → 边侧（模型预加载+人脸库预提取+课表加载）→ 云端（模型预加载+连 Broker+gRPC）→ 端侧（连 Broker+上线宣告+等课表）。
- **模型加载**：各层启动时预加载到内存，避免首次推理冷启动。
- **非上课时段**：端侧只发心跳，不执行推理。课表无课则全天休眠。严格按课表驱动。
- **任务结果格式**：每种 TaskType 有独立的结果 JSON schema，包含 result 和 metrics 两部分。face_attendance 需区分 present/absent/unknown（检测到人脸但无法匹配）。报告输出 JSON + HTML 双格式，文件存储在云端，边侧通过 HTTP 获取。
- **人脸库结构**：`/data/face_lib/` 下 students.json（花名册，含 student_id + name + photo 路径）+ photos/ 目录。启动时预提取特征向量，持久化到 embeddings/ 目录为 .npy 文件，仅在 photos 变化时重新提取。花名册为唯一数据源，absent = 花名册 - present，不在花名册中的为 unknown。
- **课表格式**：Atlas 上 JSON 文件，每条记录含 day_of_week、start_time、end_time、course_name、teacher、class_name、device_id。device_id 必填（为多端侧预留）。临时调课直接改 JSON 重启边侧服务。
- **重启恢复**：端侧重启→上线宣告→边侧识别活跃 session（`ended_at IS NULL`）→下发恢复指令（session_id + 策略）→端侧从当前时刻恢复 person_count，不补算丢失时段，历史数据不受影响。边侧重启→扫描 SQLite 活跃 session 恢复课表监听，进行中任务超时 FAILED 由教师重试。Broker+边侧都重启→QoS 1 消息若未持久化则丢失，教师按键无响应时重试即可。
- **心跳格式**：每 5 秒 QoS 0 上报，含 device_id、timestamp、load（cpu/npu/memory）、task_queue_depth、bandwidth_bytes_sent（累计值）、current_session_id、current_policy。连续 3 次未收到心跳（15s）判定离线。
- **技术选型**：端侧 Milk-V 使用 TDL SDK（C++）开发，HTTP Server 极简化；**边侧推理使用 MindX SDK mxVision**（Python 3.9，Pipeline/Model API 调用 .om 模型，DVPP 硬件加速预处理）；边侧 API 使用 FastAPI + SSE；Dashboard 纯 HTML + Vanilla JS + Chart.js；MQTT Broker 为 Mosquitto；边→云 gRPC 使用 gRPC Python；云端推理使用 ONNX Runtime / OpenCV DNN。
- **MindX SDK 选型理由**：边侧推理选用 MindX SDK mxVision 而非直接封装 PyACL/CANN。mxVision 提供 Pipeline 插件化 JSON 编排（图像解码→缩放→推理→后处理一条龙）和 Direct Model API 两种模式，内置 DVPP 硬件加速预处理、NMS 后处理等插件，减少约 90% 推理样板代码。华为官方维护与 Ascend 310P 的适配优化。Python 3.9 为 MindX SDK 硬性版本要求。约束：模型需经 ATC 工具转 .om 格式；同步推理需 `asyncio.to_thread()` 包装以兼容 FastAPI 事件循环。
- **边→云 gRPC**：边侧每 30s 向云端上报 StatusReport（CPU/NPU/内存/队列深度/连接端侧数），同时发 Heartbeat 维持存活检测。云端负载通过 MQTT 上报，调度引擎订阅以支持负载均衡策略。
- **MQTT Topic 目录**：任务通路（request/result × 端边云）+ 设备管理（online/offline + LWT）+ 心跳（heartbeat, 5s）+ 云端状态（cloud/status/report, 30s）+ 人数上报（person_count）+ 调度指令（schedule/command）。详见 topic 清单。端侧 LWT 消息到 offline topic，Broker 自动发布异常断线通知。
- **端侧 Web 视频**：首期使用静态截图（定时刷新），不做实时视频流。手机浏览器兼容性最优。Dashboard 视频预览后续可以考虑 WebRTC 方案。
- **实验模式**：管理员在 Dashboard 触发。边侧内置 benchmark 工具，依次用三种策略发送 N 个模拟任务（使用预录测试图像，不需要端侧参与）。实验期间不阻塞真实任务，结果分开统计。完成后 Dashboard 刷新 CDF 对比曲线。
- **节点配置**：每个节点一个 YAML 配置文件，包含该节点所需的所有参数（MQTT 地址、模型路径、端口号、超时阈值等）。
