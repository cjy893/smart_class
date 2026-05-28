import asyncio
import json
import time

from db.models import (
    AttendanceRecord,
    PersonCount,
    PersonCountAggregate,
    TaskStatus,
    TaskType,
)
from scheduler import Scheduler
from task_manager import TaskManager


class FakeMqtt:
    def __init__(self):
        self.published = []

    async def publish(self, topic, payload, qos=0):
        self.published.append((topic, json.loads(payload), qos))


class FixedPolicy:
    def __init__(self, target):
        self.target = target

    def decide(self, task, context):
        return self.target


class FakeTaskRepository:
    def __init__(self):
        self.tasks = {}
        self.updates = []

    async def create(self, task):
        self.tasks[task.task_id] = task
        return task.task_id

    async def update(self, task_id, **kwargs):
        self.updates.append((task_id, kwargs))
        task = self.tasks[task_id]
        for key, value in kwargs.items():
            setattr(task, key, value)

    async def get(self, task_id):
        return self.tasks.get(task_id)

    async def get_latest_attendance_attempt(self, session_id):
        return 0


class FakeBehaviorRepository:
    def __init__(self, summary=None):
        self.records = []
        self.summary = summary or {}

    async def insert_batch(self, records):
        self.records.extend(records)

    async def get_summary_by_session(self, session_id):
        return dict(self.summary)


class FakePersonCountRepository:
    def __init__(self, aggregate=None, points=None):
        self.aggregate = aggregate
        self.points = points or []

    async def get_aggregate(self, session_id):
        return self.aggregate

    async def get_by_session(self, session_id):
        return list(self.points)


class FakeAttendanceRepository:
    def __init__(self, records=None):
        self.records = records or []

    async def get_latest_by_session(self, session_id):
        return list(self.records)


def run(coro):
    return asyncio.run(coro)


def make_scheduler(policy_target="cloud", pc_repo=None, attendance_repo=None,
                   behavior_repo=None, cloud_offline_timeout_s=60):
    mqtt = FakeMqtt()
    task_repo = FakeTaskRepository()
    task_mgr = TaskManager(
        task_repo,
        mqtt,
        timeout_ms={
            "behavior_analyze": 60000,
            "report_generate": 60000,
            "face_attendance": 60000,
            "person_count": 60000,
        },
    )
    behavior_repo = behavior_repo or FakeBehaviorRepository()
    scheduler = Scheduler(
        FixedPolicy(policy_target),
        mqtt,
        task_mgr,
        task_repo,
        behavior_repo,
        person_count_repo=pc_repo,
        attendance_repo=attendance_repo,
        cloud_offline_timeout_s=cloud_offline_timeout_s,
    )
    return scheduler, mqtt, task_repo, task_mgr, behavior_repo


def sample_task(task_type="behavior_analyze", task_id="task-1"):
    return {
        "task_id": task_id,
        "task_type": task_type,
        "trigger_source": "user_button",
        "session_id": "session-1",
        "device_id": "classroom-301",
        "created_at": "2026-05-26T08:15:02",
        "image": "base64-image",
        "params": {"threshold": 0.4},
    }


def test_behavior_analyze_cloud_dispatch_preserves_original_payload():
    scheduler, mqtt, task_repo, task_mgr, _ = make_scheduler(policy_target="cloud")

    run(scheduler.handle_task_request(sample_task("behavior_analyze")))

    assert mqtt.published[0][0] == "cloud/task/request/classroom-301"
    assert mqtt.published[0][2] == 1
    payload = mqtt.published[0][1]
    assert payload["task_id"] == "task-1"
    assert payload["task_type"] == "behavior_analyze"
    assert payload["image"] == "base64-image"
    assert payload["params"] == {"threshold": 0.4}
    assert task_repo.tasks["task-1"].target_layer == "cloud"
    assert task_repo.tasks["task-1"].status == TaskStatus.DISPATCHED
    assert task_mgr.get_payload("task-1")["image"] == "base64-image"


def test_report_generate_cloud_dispatch_injects_edge_aggregate():
    aggregate = PersonCountAggregate(
        session_id="session-1",
        avg_count=31.5,
        max_count=35,
        min_count=29,
        sample_count=8,
        aggregated_at="2026-05-26T09:40:00",
    )
    pc_repo = FakePersonCountRepository(
        aggregate=aggregate,
        points=[
            PersonCount("session-1", "classroom-301", 32, "2026-05-26T08:15:00"),
            PersonCount("session-1", "classroom-301", 34, "2026-05-26T08:16:00"),
        ],
    )
    attendance_repo = FakeAttendanceRepository([
        AttendanceRecord("session-1", "att-1", "s1", "Alice", "present", "2026-05-26T08:20:00"),
        AttendanceRecord("session-1", "att-1", "s2", "Bob", "absent", "2026-05-26T08:20:00"),
        AttendanceRecord("session-1", "att-1", "", "unknown", "unknown", "2026-05-26T08:20:00"),
    ])
    behavior_repo = FakeBehaviorRepository(summary={"hand_up": 2, "talking": 1})
    scheduler, mqtt, _, _, _ = make_scheduler(
        pc_repo=pc_repo,
        attendance_repo=attendance_repo,
        behavior_repo=behavior_repo,
    )
    message = sample_task("report_generate", "report-1")
    message["params"] = {"report_type": "final"}

    run(scheduler.handle_task_request(message))

    payload = mqtt.published[0][1]
    assert payload["task_type"] == "report_generate"
    assert payload["image"] == ""
    assert payload["params"]["report_type"] == "final"
    assert payload["params"]["aggregate"] == {
        "person_count": {
            "avg": 31.5,
            "max": 35,
            "min": 29,
            "sample_count": 8,
        },
        "attendance": {
            "present": ["Alice"],
            "absent": ["Bob"],
            "unknown": 1,
        },
        "behavior": {"hand_up": 2, "talking": 1},
    }


def test_cloud_completed_result_updates_task_records_behavior_and_forwards_to_device():
    scheduler, mqtt, task_repo, task_mgr, behavior_repo = make_scheduler(policy_target="cloud")
    run(scheduler.handle_task_request(sample_task("behavior_analyze")))

    run(scheduler.handle_cloud_result({
        "task_id": "task-1",
        "task_type": "behavior_analyze",
        "session_id": "session-1",
        "device_id": "classroom-301",
        "status": "COMPLETED",
        "result": {"hand_up": 2, "standing": 0, "total_detected": 3},
        "metrics": {"inference_latency_ms": 25.0},
    }))

    task = task_repo.tasks["task-1"]
    assert task.status == TaskStatus.COMPLETED
    assert json.loads(task.result_json) == {"hand_up": 2, "standing": 0, "total_detected": 3}
    assert len(behavior_repo.records) == 1
    assert behavior_repo.records[0].executed_layer == "cloud"
    assert behavior_repo.records[0].behavior_type == "hand_up"
    topic, payload, qos = mqtt.published[-1]
    assert topic == "edge/task/result/classroom-301"
    assert qos == 1
    assert payload["status"] == "COMPLETED"
    assert payload["session_id"] == "session-1"
    assert payload["device_id"] == "classroom-301"
    assert task_mgr.get_payload("task-1") is None


def test_cloud_failed_result_marks_task_failed_and_forwards_error_to_device():
    scheduler, mqtt, task_repo, task_mgr, behavior_repo = make_scheduler(policy_target="cloud")
    run(scheduler.handle_task_request(sample_task("behavior_analyze")))

    run(scheduler.handle_cloud_result({
        "task_id": "task-1",
        "task_type": "behavior_analyze",
        "session_id": "session-1",
        "device_id": "classroom-301",
        "status": "FAILED",
        "result": {},
        "metrics": {},
        "error": "invalid base64 image",
    }))

    assert task_repo.tasks["task-1"].status == TaskStatus.FAILED
    assert behavior_repo.records == []
    topic, payload, qos = mqtt.published[-1]
    assert topic == "edge/task/result/classroom-301"
    assert qos == 1
    assert payload["status"] == "FAILED"
    assert payload["error"] == "invalid base64 image"
    assert task_mgr.get_payload("task-1") is None


def test_cloud_rejected_result_marks_task_rejected_and_forwards_error_to_device():
    scheduler, mqtt, task_repo, task_mgr, behavior_repo = make_scheduler(policy_target="cloud")
    run(scheduler.handle_task_request(sample_task("behavior_analyze")))

    run(scheduler.handle_cloud_result({
        "task_id": "task-1",
        "task_type": "behavior_analyze",
        "session_id": "session-1",
        "device_id": "classroom-301",
        "status": "REJECTED",
        "result": {},
        "metrics": {},
        "error": "unsupported task_type",
    }))

    assert task_repo.tasks["task-1"].status == TaskStatus.REJECTED
    assert behavior_repo.records == []
    topic, payload, qos = mqtt.published[-1]
    assert topic == "edge/task/result/classroom-301"
    assert qos == 1
    assert payload["status"] == "REJECTED"
    assert payload["error"] == "unsupported task_type"
    assert task_mgr.get_payload("task-1") is None


def test_cloud_offline_timeout_uses_configured_seconds_for_routing():
    scheduler, mqtt, task_repo, _, _ = make_scheduler(
        policy_target="cloud",
        cloud_offline_timeout_s=2,
    )
    scheduler._cloud_last_seen = time.time() - 3

    run(scheduler.check_cloud_offline())
    run(scheduler.handle_task_request(sample_task("report_generate", "report-1")))

    task = task_repo.tasks["report-1"]
    assert task.status == TaskStatus.REJECTED
    topic, payload, qos = mqtt.published[-1]
    assert topic == "edge/task/result/classroom-301"
    assert qos == 1
    assert payload["status"] == "REJECTED"
    assert payload["task_type"] == "report_generate"
