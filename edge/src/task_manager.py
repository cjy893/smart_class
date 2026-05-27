import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from db.models import Task, TaskStatus, TaskType
from db.repository import TaskRepository
from mqtt_client import MqttClient

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = {
    "person_count": 3000,
    "face_attendance": 15000,
    "behavior_analyze": 30000,
    "report_generate": 30000,
}


class TaskManager:
    """Task 生命周期管理 + 超时监控 + 幂等去重。"""

    def __init__(self, task_repo: TaskRepository, mqtt: MqttClient,
                 timeout_ms: dict[str, int] | None = None,
                 dedup_window_seconds: int = 300):
        self.task_repo = task_repo
        self.mqtt = mqtt
        self.timeout_ms = timeout_ms or DEFAULT_TIMEOUT_MS
        self.dedup_window = dedup_window_seconds
        self._seen_tasks: dict[str, float] = {}  # task_id → created_timestamp
        self._payload_cache: dict[str, dict] = {}
        self._running_timeouts: dict[str, asyncio.Task] = {}
        self._local_queue: list[Task] = []
        self._queue_lock = asyncio.Lock()

    async def create_task(self, msg: dict) -> Optional[Task]:
        """从 MQTT 消息创建 Task 记录。返回 None 表示重复。"""
        task_id = msg["task_id"]

        if self.is_duplicate(task_id):
            logger.info("Duplicate task ignored: %s", task_id)
            return None

        self._seen_tasks[task_id] = asyncio.get_event_loop().time()
        self._payload_cache[task_id] = dict(msg)

        timeout_ms = self.timeout_ms.get(msg["task_type"], 30000)
        created_at = msg.get("created_at", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
        timeout_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")  # approximate

        t = Task(
            task_id=task_id,
            task_type=msg["task_type"],
            trigger_source=msg.get("trigger_source", "user_button"),
            session_id=msg.get("session_id", ""),
            device_id=msg.get("device_id", ""),
            created_at=created_at,
            status=TaskStatus.CREATED,
            timeout_at=timeout_at,
        )
        await self.task_repo.create(t)
        await self._arm_timeout(t, timeout_ms / 1000.0)
        return t

    def is_duplicate(self, task_id: str) -> bool:
        return task_id in self._seen_tasks

    def get_payload(self, task_id: str) -> Optional[dict]:
        payload = self._payload_cache.get(task_id)
        return dict(payload) if payload is not None else None

    async def update_status(self, task_id: str, status: str) -> None:
        await self.task_repo.update(task_id, status=status)
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.REJECTED):
            self._cancel_timeout(task_id)
            self._payload_cache.pop(task_id, None)

    async def handle_result(self, task_id: str, result: dict) -> None:
        """处理执行后返回的结果。"""
        completed_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        await self.task_repo.update(
            task_id,
            status=TaskStatus.COMPLETED,
            result_json=json.dumps(result.get("result", {})),
            metrics_json=json.dumps(result.get("metrics", {})),
            completed_at=completed_at,
        )
        self._cancel_timeout(task_id)
        self._payload_cache.pop(task_id, None)

    async def record_face_attendance(self, task_id: str, session_id: str,
                                     result: dict, metrics: dict) -> None:
        """特殊处理：签到任务更新 attempt 字段。"""
        current = await self.task_repo.get_latest_attendance_attempt(session_id)
        await self.task_repo.update(
            task_id,
            status=TaskStatus.COMPLETED,
            result_json=json.dumps(result),
            metrics_json=json.dumps(metrics),
            completed_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            attempt=current + 1,
        )
        self._cancel_timeout(task_id)
        self._payload_cache.pop(task_id, None)

    async def enqueue_local(self, task: Task) -> None:
        """将任务加入边侧本地执行队列。"""
        async with self._queue_lock:
            self._local_queue.append(task)
        await self.update_status(task.task_id, TaskStatus.QUEUED)

    async def dequeue_local(self) -> Optional[Task]:
        async with self._queue_lock:
            if self._local_queue:
                return self._local_queue.pop(0)
            return None

    def get_queue_depth(self) -> int:
        return len(self._local_queue)

    async def _arm_timeout(self, task: Task, timeout_seconds: float) -> None:
        async def _on_timeout():
            await asyncio.sleep(timeout_seconds)
            current = await self.task_repo.get(task.task_id)
            if current and current.status not in (
                TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.REJECTED
            ):
                logger.warning("Task timeout: %s (%s)", task.task_id, task.task_type)
                await self.update_status(task.task_id, TaskStatus.FAILED)

        self._cancel_timeout(task.task_id)
        self._running_timeouts[task.task_id] = asyncio.create_task(_on_timeout())

    def _cancel_timeout(self, task_id: str) -> None:
        t = self._running_timeouts.pop(task_id, None)
        if t:
            t.cancel()
