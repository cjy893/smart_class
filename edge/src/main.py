#!/usr/bin/env python3
"""边侧服务入口 —— 启动顺序编排。

启动流程:
  1. 加载 edge_config.yaml
  2. 加载 schedule.json
  3. SQLite 初始化 (schema.sql)
  4. MindX SDK 初始化 + 模型预加载 (.om)
  5. 人脸库加载 + 特征预提取/缓存
  6. MQTT 连接 + 订阅所有 topic
  7. Session 恢复 (扫描活跃 session)
  8. ScheduleLoader 启动定时检查
  9. 调度引擎启动
  10. gRPC 客户端启动
  11. FastAPI 启动
"""

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

import yaml

# 确保 src 在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.connection import Connection
from db.repository import (
    AttendanceRepository, BehaviorRepository,
    PersonCountRepository, SessionRepository, TaskRepository,
)
from api.server import create_app
from api.routes import create_router
from api.sse import SseManager
from face_lib import FaceLib
from grpc_client import GrpcClient
from inference.inference_service import InferenceService
from inference.face_engine import FaceEngine
from inference.behavior_engine import BehaviorEngine
from mqtt_client import MqttClient
from policy import AdaptivePolicy, GreedyNearbyPolicy, LoadBalancePolicy
from scheduler import Scheduler
from schedule_loader import ScheduleLoader
from session_manager import SessionManager
from task_manager import TaskManager

logger = logging.getLogger(__name__)

POLICY_MAP = {
    "greedy_nearby": GreedyNearbyPolicy,
    "load_balance": LoadBalancePolicy,
    "adaptive": AdaptivePolicy,
}


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 项目根目录 (edge/)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "edge_config.yaml")
    config = load_config(config_path)
    logger.info("Config loaded: %s", config_path)

    # 路径：优先用 config 中的绝对路径，否则回退到项目相对路径
    paths = config.get("paths", {})
    db_path = paths.get("sqlite_db") or os.path.join(base_dir, "data", "edge.db")
    schedule_path = paths.get("schedule") or os.path.join(base_dir, "config", "schedule.json")
    face_lib_path = paths.get("face_lib") or os.path.join(base_dir, "data", "face_lib")
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "db", "schema.sql")

    # --- Step 1: DB ---
    db_conn = Connection(db_path, schema_path)
    conn = await db_conn.init()
    logger.info("SQLite initialized: %s", db_path)

    session_repo = SessionRepository(conn)
    task_repo = TaskRepository(conn)
    pc_repo = PersonCountRepository(conn)
    attendance_repo = AttendanceRepository(conn)
    behavior_repo = BehaviorRepository(conn)

    # --- Step 2: MQTT ---
    mqtt = MqttClient(
        broker_host=config["mqtt"]["broker_host"],
        broker_port=config["mqtt"]["broker_port"],
        client_id=config["device_id"],
    )
    await mqtt.connect()
    logger.info("MQTT connected")

    # --- Step 3: Session recovery ---
    session_mgr = SessionManager(session_repo, pc_repo, mqtt)
    active_sessions = await session_mgr.recover_active_sessions()
    logger.info("Recovered %d active sessions", len(active_sessions))

    # --- Step 4: MindX SDK + Models ---
    inf_cfg = config["inference"]
    inference_svc = InferenceService(
        mindx_home=config["paths"]["mindx_home"],
        device_id=inf_cfg.get("device_id", 0),
    )
    if inf_cfg.get("preload_models", True):
        await inference_svc.init({
            "face_detection": inf_cfg["face_detection_model"],
            "face_recognition": inf_cfg["face_recognition_model"],
            "behavior": inf_cfg["behavior_model"],
        })
        logger.info("Models preloaded via MindX SDK")

    # --- Step 5: Face lib ---
    face_lib = FaceLib(face_lib_path)
    face_engine = FaceEngine(inference_svc)
    await face_lib.init(face_engine)
    logger.info("FaceLib initialized: %d students, %d embeddings",
                 len(face_lib.students), len(face_lib.embeddings))

    # --- Step 6: Task manager ---
    task_mgr = TaskManager(
        task_repo=task_repo,
        mqtt=mqtt,
        timeout_ms={
            "person_count": config["scheduler"]["timeout_person_count_ms"],
            "face_attendance": config["scheduler"]["timeout_face_attendance_ms"],
            "behavior_analyze": config["scheduler"]["timeout_behavior_analyze_ms"],
            "report_generate": config["scheduler"]["timeout_report_generate_ms"],
        },
        dedup_window_seconds=config["scheduler"]["dedup_window_seconds"],
    )

    # --- Step 7: Policy + Scheduler ---
    policy_cls = POLICY_MAP.get(config["scheduler"]["policy"], AdaptivePolicy)
    policy = policy_cls()
    behavior_engine = BehaviorEngine(inference_svc)

    scheduler = Scheduler(
        policy,
        mqtt,
        task_mgr,
        task_repo,
        behavior_repo,
        person_count_repo=pc_repo,
        attendance_repo=attendance_repo,
        cloud_offline_timeout_s=config["scheduler"]["cloud_offline_timeout_s"],
    )
    scheduler.set_engines(face_engine, behavior_engine, face_lib)
    logger.info("Scheduler initialized, policy=%s", config["scheduler"]["policy"])

    # --- Step 8: MQTT subscriptions ---
    async def on_task_request(topic: str, payload: str):
        msg = json.loads(payload)
        task_type = msg.get("task_type", "")
        # person_count 是推送数据流，走独立 topic，不经过调度引擎
        if task_type == "person_count":
            return
        await scheduler.handle_task_request(msg)

    async def on_cloud_result(topic: str, payload: str):
        await scheduler.handle_cloud_result(json.loads(payload))

    async def on_cloud_status(topic: str, payload: str):
        await scheduler.handle_cloud_status(json.loads(payload))

    async def on_person_count(topic: str, payload: str):
        msg = json.loads(payload)
        result = msg.get("result", {})
        from db.models import PersonCount
        await pc_repo.insert(PersonCount(
            session_id=msg.get("session_id", ""),
            device_id=msg.get("device_id", ""),
            count=result.get("count", 0),
            timestamp=result.get("timestamp", ""),
        ))

    async def on_device_online(topic: str, payload: str):
        msg = json.loads(payload)
        device_id = msg.get("device_id", "")
        logger.info("Device online: %s (looking for active session)", device_id)
        s = await session_repo.get_active(device_id)
        logger.info("Active session for %s: %s", device_id, s.session_id if s else "NONE")
        if s:
            cmd = {
                "command": "session_restore",
                "session_id": s.session_id,
                "policy": config["scheduler"]["policy"],
            }
            await mqtt.publish(
                f"edge/schedule/command/{device_id}",
                json.dumps(cmd),
                qos=1,
            )
            logger.info("session_restore sent to %s", device_id)

    async def on_device_offline(topic: str, payload: str):
        msg = json.loads(payload)
        device_id = msg.get("device_id", "")
        logger.warning("Device offline: %s (possible abnormal disconnect)", device_id)

    await mqtt.subscribe("edge/task/request/#", 1, on_task_request)
    await mqtt.subscribe("cloud/task/result/#", 1, on_cloud_result)
    await mqtt.subscribe("cloud/status/report", 0, on_cloud_status)
    await mqtt.subscribe("edge/status/person_count/#", 0, on_person_count)
    await mqtt.subscribe("edge/device/online/#", 1, on_device_online)
    await mqtt.subscribe("edge/device/offline/#", 1, on_device_offline)
    logger.info("MQTT subscriptions set up")

    # --- Step 9: Schedule loader ---
    schedule_loader = ScheduleLoader(schedule_path)
    schedule_loader.load()

    schedule_loader.on_class_start(lambda entry: session_mgr.start_session(entry))
    async def on_class_end(entry: dict):
        device = config["device_id"]
        s = await session_repo.get_active(device)
        if s:
            await session_mgr.end_session(s.session_id)
            # 下课触发报告生成
            report_msg = {
                "task_id": f"report_{s.session_id}",
                "task_type": "report_generate",
                "trigger_source": "system_timer",
                "session_id": s.session_id,
                "device_id": device,
                "created_at": entry.get("end_time", ""),
                "image": "",
            }
            await scheduler.handle_task_request(report_msg)
            logger.info("Session ended: %s, report task created", s.session_id)

    schedule_loader.on_class_end(on_class_end)

    async def periodic_checks():
        """定时任务：本地队列异步消费、云端离线检测。"""
        while True:
            # 本地队列串行消费
            task = await task_mgr.dequeue_local()
            if task:
                asyncio.create_task(scheduler._execute_local(task))

            # 云端离线检测
            await scheduler.check_cloud_offline()

            await asyncio.sleep(0.1)

    asyncio.create_task(schedule_loader.start())
    asyncio.create_task(periodic_checks())
    logger.info("ScheduleLoader and periodic checks started")

    # --- Step 10: gRPC ---
    grpc_client = GrpcClient(
        cloud_address=config["grpc"]["cloud_address"],
        edge_id=config["device_id"],
    )
    asyncio.create_task(grpc_client.start(
        interval_seconds=config["grpc"]["report_interval_seconds"]
    ))

    # --- Step 11: FastAPI + SSE ---
    sse_mgr = SseManager()
    app = create_app()
    router = create_router(session_repo, pc_repo, attendance_repo,
                           behavior_repo, sse_mgr, scheduler)

    @app.get("/api/v1/events")
    async def events(request):
        return await sse_mgr.register(request)

    app.include_router(router)

    import uvicorn
    api_cfg = config["api"]
    server = uvicorn.Server(uvicorn.Config(
        app, host=api_cfg["host"], port=api_cfg["port"], log_level="info",
    ))

    logger.info("Starting API server on %s:%d", api_cfg["host"], api_cfg["port"])
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
