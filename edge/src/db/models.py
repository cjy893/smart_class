from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class TaskType(str, Enum):
    PERSON_COUNT = "person_count"
    FACE_ATTENDANCE = "face_attendance"
    BEHAVIOR_ANALYZE = "behavior_analyze"
    REPORT_GENERATE = "report_generate"


class TaskStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class TriggerSource(str, Enum):
    SYSTEM_TIMER = "system_timer"
    USER_BUTTON = "user_button"
    DASHBOARD_MANUAL = "dashboard_manual"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"


class AttendanceStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


@dataclass
class Session:
    session_id: str
    device_id: str
    start_time: str
    course_name: Optional[str] = None
    teacher: Optional[str] = None
    class_name: Optional[str] = None
    ended_at: Optional[str] = None
    status: str = "active"
    created_at: Optional[str] = None


@dataclass
class Task:
    task_id: str
    task_type: str
    trigger_source: str
    session_id: str
    device_id: str
    created_at: str
    status: str = "CREATED"
    target_layer: Optional[str] = None
    result_json: Optional[str] = None
    metrics_json: Optional[str] = None
    completed_at: Optional[str] = None
    timeout_at: Optional[str] = None
    attempt: int = 1


@dataclass
class PersonCount:
    session_id: str
    device_id: str
    count: int
    timestamp: str
    id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class PersonCountAggregate:
    session_id: str
    avg_count: float
    max_count: int
    min_count: int
    sample_count: int
    aggregated_at: str


@dataclass
class AttendanceRecord:
    session_id: str
    task_id: str
    student_id: str
    student_name: str
    status: str
    timestamp: str
    confidence: Optional[float] = None
    id: Optional[int] = None


@dataclass
class BehaviorRecord:
    session_id: str
    task_id: str
    executed_layer: str
    behavior_type: str
    count: int
    timestamp: str
    id: Optional[int] = None
