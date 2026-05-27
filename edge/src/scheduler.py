import asyncio
import json
import logging
import time
from typing import Optional

from db.models import Task, TaskStatus, TaskType
from db.repository import TaskRepository, BehaviorRepository
from mqtt_client import MqttClient
from policy import Policy, SchedulingContext
from task_manager import TaskManager

logger = logging.getLogger(__name__)

HARD_CONSTRAINT_DEVICE = {TaskType.PERSON_COUNT}
HARD_CONSTRAINT_EDGE = {TaskType.FACE_ATTENDANCE}
HARD_CONSTRAINT_CLOUD = {TaskType.REPORT_GENERATE}


class Scheduler:
    """调度引擎：接收 MQTT 任务请求，按策略决策目标层，路由执行。"""

    def __init__(self, policy: Policy, mqtt: MqttClient, task_mgr: TaskManager,
                 task_repo: TaskRepository, behavior_repo: BehaviorRepository):
        self.policy = policy
        self.mqtt = mqtt
        self.task_mgr = task_mgr
        self.task_repo = task_repo
        self.behavior_repo = behavior_repo
        self.context = SchedulingContext()
        self._cloud_online = True
        self._cloud_last_seen = time.time()
        self._face_engine: Optional["FaceEngine"] = None
        self._behavior_engine: Optional["BehaviorEngine"] = None
        self._face_lib: Optional["FaceLib"] = None

    def set_engines(self, face_engine: "FaceEngine",
                    behavior_engine: "BehaviorEngine",
                    face_lib: "FaceLib") -> None:
        self._face_engine = face_engine
        self._behavior_engine = behavior_engine
        self._face_lib = face_lib

    async def handle_task_request(self, message: dict) -> None:
        """MQTT 回调入口：edge/task/request/{device_id}。"""
        task = await self.task_mgr.create_task(message)
        if task is None:
            return  # 重复任务

        task_type = TaskType(message["task_type"])
        device_id = message.get("device_id", "")

        # 硬约束路由
        if task_type in HARD_CONSTRAINT_DEVICE:
            target = "device"
        elif task_type in HARD_CONSTRAINT_EDGE:
            target = "edge"
        elif task_type in HARD_CONSTRAINT_CLOUD:
            target = "cloud"
            if not self._cloud_online:
                await self.task_mgr.update_status(task.task_id, TaskStatus.REJECTED)
                await self._send_result(device_id, task.task_id, task_type,
                                        TaskStatus.REJECTED, {}, {})
                return
        elif task_type == TaskType.BEHAVIOR_ANALYZE:
            if not self._cloud_online:
                target = "edge"
            else:
                target = self.policy.decide(task, self.context)
        else:
            target = "edge"

        await self.dispatch(task, target)

    async def dispatch(self, task: Task, target: str) -> None:
        """路由到目标层执行。"""
        device_id = task.device_id
        task_type = TaskType(task.task_type)

        await self.task_repo.update(task.task_id, target_layer=target)

        if target == "device":
            # person_count 透传，端侧自闭环
            await self.task_mgr.update_status(task.task_id, TaskStatus.COMPLETED)

        elif target == "edge":
            await self.task_mgr.enqueue_local(task)
            await self._execute_local(task)

        elif target == "cloud":
            # 转发到云
            payload = {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "trigger_source": task.trigger_source,
                "session_id": task.session_id,
                "device_id": task.device_id,
                "created_at": task.created_at,
                "image": "",
                "params": {},
            }
            await self.mqtt.publish(
                f"cloud/task/request/{device_id}",
                json.dumps(payload),
                qos=1,
            )
            await self.task_mgr.update_status(task.task_id, TaskStatus.DISPATCHED)

    async def _execute_local(self, task: Task) -> None:
        """边侧本地执行推理任务。"""
        task_type = TaskType(task.task_type)
        await self.task_mgr.update_status(task.task_id, TaskStatus.EXECUTING)

        try:
            if task_type == TaskType.FACE_ATTENDANCE:
                await self._run_face_attendance(task)
            elif task_type == TaskType.BEHAVIOR_ANALYZE:
                await self._run_behavior_analyze(task)
            else:
                await self.task_mgr.update_status(task.task_id, TaskStatus.FAILED)
        except Exception as e:
            logger.error("Local execution failed for %s: %s", task.task_id, e)
            await self.task_mgr.update_status(task.task_id, TaskStatus.FAILED)

    async def _run_face_attendance(self, task: Task) -> None:
        if not self._face_engine or not self._face_lib:
            await self.task_mgr.update_status(task.task_id, TaskStatus.FAILED)
            return

        # 从 task 获取图像数据
        t0 = time.perf_counter()
        task_record = await self.task_repo.get(task.task_id)
        if not task_record:
            return

        # 图像从 MQTT 消息传过来，这里用 task_record 中暂存的 image 字段
        # 实际需要从 MQTT 消息携带 image base64，此处简化处理
        image_bytes = b""  # placeholder: 实际应从 MQTT 消息中获取
        result = await self._face_engine.recognize(image_bytes, self._face_lib)
        t1 = time.perf_counter()

        present_names = [s["name"] for s in result.present]
        absent_names = [s["name"] for s in result.absent]

        result_dict = {
            "present": present_names,
            "absent": absent_names,
            "unknown": result.unknown,
            "total_expected": result.total_expected,
            "attempt": result.attempt,
        }
        metrics = {
            "inference_latency_ms": (t1 - t0) * 1000,
            "end_to_end_latency_ms": (t1 - t0) * 1000,
        }

        # 写入签到记录
        from db.models import AttendanceRecord, AttendanceStatus
        records = []
        now = task.created_at
        for s in self._face_lib.students:
            status = AttendanceStatus.PRESENT if s.student_id in {
                x["student_id"] for x in result.present
            } else AttendanceStatus.ABSENT
            records.append(AttendanceRecord(
                session_id=task.session_id,
                task_id=task.task_id,
                student_id=s.student_id,
                student_name=s.name,
                status=status,
                timestamp=now,
            ))
        # 记录 unknown 人脸
        for _ in range(result.unknown):
            records.append(AttendanceRecord(
                session_id=task.session_id,
                task_id=task.task_id,
                student_id="",
                student_name="unknown",
                status=AttendanceStatus.UNKNOWN,
                timestamp=now,
            ))

        from db.repository import AttendanceRepository
        attend_repo = AttendanceRepository(self.task_repo.conn)
        await attend_repo.insert_batch(records)

        await self.task_mgr.record_face_attendance(
            task.task_id, task.session_id, result_dict, metrics)
        await self._send_result(task.device_id, task.task_id,
                                TaskType.FACE_ATTENDANCE, TaskStatus.COMPLETED,
                                result_dict, metrics)

    async def _run_behavior_analyze(self, task: Task) -> None:
        if not self._behavior_engine:
            await self.task_mgr.update_status(task.task_id, TaskStatus.FAILED)
            return

        t0 = time.perf_counter()
        image_bytes = b""  # placeholder
        result = await self._behavior_engine.analyze(image_bytes)
        t1 = time.perf_counter()

        result_dict = result.to_dict()
        metrics = {"inference_latency_ms": (t1 - t0) * 1000}

        # 写入行为记录
        records = []
        for btype, count in [
            ("hand_up", result.hand_up),
            ("standing", result.standing),
            ("head_down", result.head_down),
            ("talking", result.talking),
        ]:
            if count > 0:
                from db.models import BehaviorRecord
                records.append(BehaviorRecord(
                    session_id=task.session_id,
                    task_id=task.task_id,
                    executed_layer="edge",
                    behavior_type=btype,
                    count=count,
                    timestamp=task.created_at,
                ))
        if records:
            await self.behavior_repo.insert_batch(records)

        await self.task_mgr.handle_result(task.task_id, {
            "result": result_dict,
            "metrics": metrics,
        })
        await self._send_result(task.device_id, task.task_id,
                                TaskType.BEHAVIOR_ANALYZE, TaskStatus.COMPLETED,
                                result_dict, metrics)

    async def handle_cloud_result(self, message: dict) -> None:
        """云端结果回调。"""
        task_id = message.get("task_id", "")
        device_id = message.get("device_id", "")
        task = await self.task_repo.get(task_id)
        if not task:
            return

        result = message.get("result", {})
        metrics = message.get("metrics", {})
        task_type = TaskType(task.task_type)

        if task_type == TaskType.BEHAVIOR_ANALYZE:
            records = []
            for btype, count in result.items():
                if btype == "total_detected":
                    continue
                if count > 0:
                    from db.models import BehaviorRecord
                    records.append(BehaviorRecord(
                        session_id=task.session_id,
                        task_id=task_id,
                        executed_layer="cloud",
                        behavior_type=btype,
                        count=count,
                        timestamp=task.created_at,
                    ))
            if records:
                await self.behavior_repo.insert_batch(records)

        await self.task_mgr.handle_result(task_id, {
            "result": result,
            "metrics": metrics,
        })

        # 转发结果到端侧
        payload = {
            "task_id": task_id,
            "task_type": task.task_type,
            "status": TaskStatus.COMPLETED,
            "result": result,
            "metrics": metrics,
        }
        await self.mqtt.publish(
            f"edge/task/result/{device_id}",
            json.dumps(payload),
            qos=1,
        )

    async def handle_cloud_status(self, message: dict) -> None:
        """处理云端状态上报，更新 SchedulingContext。"""
        load = message.get("load", {})
        self.context.cloud_load = load.get("cpu_percent", 0)
        self.context.cloud_queue_depth = message.get("task_queue_depth", 0)
        self._cloud_online = True
        self._cloud_last_seen = time.time()

    async def check_cloud_offline(self) -> None:
        """定时检查云端是否超时未上报。"""
        if time.time() - self._cloud_last_seen > 60:
            self._cloud_online = False

    async def _send_result(self, device_id: str, task_id: str,
                           task_type: TaskType, status: TaskStatus,
                           result: dict, metrics: dict) -> None:
        payload = {
            "task_id": task_id,
            "task_type": task_type,
            "status": status,
            "result": result,
            "metrics": metrics,
        }
        await self.mqtt.publish(
            f"edge/task/result/{device_id}",
            json.dumps(payload),
            qos=1,
        )

    def get_stats(self) -> dict:
        return {
            "edge_load": self.context.edge_load,
            "cloud_load": self.context.cloud_load,
            "edge_queue_depth": self.task_mgr.get_queue_depth(),
            "cloud_queue_depth": self.context.cloud_queue_depth,
            "cloud_online": self._cloud_online,
        }
