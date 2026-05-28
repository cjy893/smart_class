import asyncio

from db.models import TaskStatus
from task_manager import TaskManager


class FakeTaskRepository:
    def __init__(self):
        self.created = {}
        self.updated = []

    async def create(self, task):
        self.created[task.task_id] = task
        return task.task_id

    async def update(self, task_id, **kwargs):
        self.updated.append((task_id, kwargs))
        task = self.created[task_id]
        for key, value in kwargs.items():
            setattr(task, key, value)

    async def get(self, task_id):
        return self.created.get(task_id)

    async def get_latest_attendance_attempt(self, session_id):
        return 0


def run(coro):
    return asyncio.run(coro)


def sample_message():
    return {
        "task_id": "task-1",
        "task_type": "behavior_analyze",
        "trigger_source": "user_button",
        "session_id": "session-1",
        "device_id": "classroom-301",
        "created_at": "2026-05-26T08:15:02",
        "image": "base64-image",
        "params": {"threshold": 0.4},
    }


def test_create_task_caches_original_payload_for_dispatch():
    manager = TaskManager(FakeTaskRepository(), mqtt=None)
    task = run(manager.create_task(sample_message()))

    assert task.task_id == "task-1"
    assert manager.get_payload("task-1") == sample_message()


def test_duplicate_task_does_not_replace_cached_payload():
    manager = TaskManager(FakeTaskRepository(), mqtt=None)
    run(manager.create_task(sample_message()))
    duplicate = sample_message()
    duplicate["image"] = "different-image"

    task = run(manager.create_task(duplicate))

    assert task is None
    assert manager.get_payload("task-1")["image"] == "base64-image"


def test_terminal_status_clears_cached_payload():
    manager = TaskManager(FakeTaskRepository(), mqtt=None)
    run(manager.create_task(sample_message()))

    run(manager.update_status("task-1", TaskStatus.FAILED))

    assert manager.get_payload("task-1") is None


def test_handle_result_clears_cached_payload():
    manager = TaskManager(FakeTaskRepository(), mqtt=None)
    run(manager.create_task(sample_message()))

    run(manager.handle_result("task-1", {
        "result": {"hand_up": 1},
        "metrics": {"inference_latency_ms": 12.0},
    }))

    assert manager.get_payload("task-1") is None
