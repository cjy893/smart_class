import sqlite3
import json
from typing import Optional
from db.models import (
    Session, Task, PersonCount, PersonCountAggregate,
    AttendanceRecord, BehaviorRecord,
)


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        session_id=row["session_id"],
        device_id=row["device_id"],
        course_name=row["course_name"],
        teacher=row["teacher"],
        class_name=row["class_name"],
        start_time=row["start_time"],
        ended_at=row["ended_at"],
        status=row["status"],
        created_at=row["created_at"],
    )


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        task_id=row["task_id"],
        task_type=row["task_type"],
        trigger_source=row["trigger_source"],
        session_id=row["session_id"],
        device_id=row["device_id"],
        status=row["status"],
        target_layer=row["target_layer"],
        result_json=row["result_json"],
        metrics_json=row["metrics_json"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        timeout_at=row["timeout_at"],
        attempt=row["attempt"],
    )


def _row_to_person_count(row: sqlite3.Row) -> PersonCount:
    return PersonCount(
        id=row["id"],
        session_id=row["session_id"],
        device_id=row["device_id"],
        count=row["count"],
        timestamp=row["timestamp"],
        created_at=row["created_at"],
    )


def _row_to_attendance(row: sqlite3.Row) -> AttendanceRecord:
    return AttendanceRecord(
        id=row["id"],
        session_id=row["session_id"],
        task_id=row["task_id"],
        student_id=row["student_id"],
        student_name=row["student_name"],
        status=row["status"],
        confidence=row["confidence"],
        timestamp=row["timestamp"],
    )


def _row_to_behavior(row: sqlite3.Row) -> BehaviorRecord:
    return BehaviorRecord(
        id=row["id"],
        session_id=row["session_id"],
        task_id=row["task_id"],
        executed_layer=row["executed_layer"],
        behavior_type=row["behavior_type"],
        count=row["count"],
        timestamp=row["timestamp"],
    )


class SessionRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    async def create(self, s: Session) -> str:
        self.conn.execute(
            """INSERT INTO session (session_id, device_id, course_name, teacher,
               class_name, start_time, ended_at, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (s.session_id, s.device_id, s.course_name, s.teacher,
             s.class_name, s.start_time, s.ended_at, s.status),
        )
        self.conn.commit()
        return s.session_id

    async def end(self, session_id: str, ended_at: str) -> None:
        self.conn.execute(
            "UPDATE session SET ended_at = ?, status = 'completed' WHERE session_id = ?",
            (ended_at, session_id),
        )
        self.conn.commit()

    async def get_active(self, device_id: str) -> Optional[Session]:
        row = self.conn.execute(
            "SELECT * FROM session WHERE device_id = ? AND ended_at IS NULL",
            (device_id,),
        ).fetchone()
        return _row_to_session(row) if row else None

    async def list_active(self) -> list[Session]:
        rows = self.conn.execute(
            "SELECT * FROM session WHERE ended_at IS NULL"
        ).fetchall()
        return [_row_to_session(r) for r in rows]

    async def get(self, session_id: str) -> Optional[Session]:
        row = self.conn.execute(
            "SELECT * FROM session WHERE session_id = ?", (session_id,)
        ).fetchone()
        return _row_to_session(row) if row else None


class TaskRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    async def create(self, t: Task) -> str:
        self.conn.execute(
            """INSERT INTO task (task_id, task_type, trigger_source, session_id,
               device_id, status, target_layer, result_json, metrics_json,
               created_at, completed_at, timeout_at, attempt)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (t.task_id, t.task_type, t.trigger_source, t.session_id,
             t.device_id, t.status, t.target_layer, t.result_json,
             t.metrics_json, t.created_at, t.completed_at, t.timeout_at, t.attempt),
        )
        self.conn.commit()
        return t.task_id

    async def update(self, task_id: str, **kwargs) -> None:
        if not kwargs:
            return
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        self.conn.execute(f"UPDATE task SET {sets} WHERE task_id = ?", values)
        self.conn.commit()

    async def get(self, task_id: str) -> Optional[Task]:
        row = self.conn.execute(
            "SELECT * FROM task WHERE task_id = ?", (task_id,)
        ).fetchone()
        return _row_to_task(row) if row else None

    async def exists(self, task_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM task WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row is not None

    async def get_latest_attendance_attempt(self, session_id: str) -> int:
        row = self.conn.execute(
            """SELECT COALESCE(MAX(attempt), 0) FROM task
               WHERE session_id = ? AND task_type = 'face_attendance'""",
            (session_id,),
        ).fetchone()
        return row[0]

    async def list_by_session(self, session_id: str) -> list[Task]:
        rows = self.conn.execute(
            "SELECT * FROM task WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]


class PersonCountRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    async def insert(self, pc: PersonCount) -> int:
        cur = self.conn.execute(
            """INSERT INTO person_count (session_id, device_id, count, timestamp)
               VALUES (?, ?, ?, ?)""",
            (pc.session_id, pc.device_id, pc.count, pc.timestamp),
        )
        self.conn.commit()
        return cur.lastrowid

    async def get_by_session(self, session_id: str) -> list[PersonCount]:
        rows = self.conn.execute(
            "SELECT * FROM person_count WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        return [_row_to_person_count(r) for r in rows]

    async def aggregate_and_prune(self, session_id: str) -> PersonCountAggregate:
        row = self.conn.execute(
            """SELECT AVG(count), MAX(count), MIN(count), COUNT(*)
               FROM person_count WHERE session_id = ?""",
            (session_id,),
        ).fetchone()
        agg = PersonCountAggregate(
            session_id=session_id,
            avg_count=round(row[0], 1) if row[0] else 0,
            max_count=row[1] or 0,
            min_count=row[2] or 0,
            sample_count=row[3] or 0,
            aggregated_at="",
        )
        agg.aggregated_at = ""  # set by caller
        self.conn.execute(
            """INSERT OR REPLACE INTO person_count_aggregate
               (session_id, avg_count, max_count, min_count, sample_count, aggregated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (agg.session_id, agg.avg_count, agg.max_count, agg.min_count, agg.sample_count),
        )
        # 仅保留当天原始点
        self.conn.execute(
            "DELETE FROM person_count WHERE session_id = ?", (session_id,)
        )
        self.conn.commit()
        return agg

    async def get_aggregate(self, session_id: str) -> Optional[PersonCountAggregate]:
        row = self.conn.execute(
            "SELECT * FROM person_count_aggregate WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return PersonCountAggregate(
            session_id=row["session_id"],
            avg_count=row["avg_count"],
            max_count=row["max_count"],
            min_count=row["min_count"],
            sample_count=row["sample_count"],
            aggregated_at=row["aggregated_at"],
        )


class AttendanceRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    async def insert_batch(self, records: list[AttendanceRecord]) -> None:
        self.conn.executemany(
            """INSERT INTO attendance_record (session_id, task_id, student_id,
               student_name, status, confidence, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(r.session_id, r.task_id, r.student_id, r.student_name,
              r.status, r.confidence, r.timestamp) for r in records],
        )
        self.conn.commit()

    async def get_latest_by_session(self, session_id: str) -> list[AttendanceRecord]:
        # 取最新一次 task 的签到记录
        latest_task = self.conn.execute(
            """SELECT task_id FROM task
               WHERE session_id = ? AND task_type = 'face_attendance'
               ORDER BY created_at DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
        if not latest_task:
            return []
        rows = self.conn.execute(
            "SELECT * FROM attendance_record WHERE task_id = ?",
            (latest_task["task_id"],),
        ).fetchall()
        return [_row_to_attendance(r) for r in rows]


class BehaviorRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    async def insert_batch(self, records: list[BehaviorRecord]) -> None:
        self.conn.executemany(
            """INSERT INTO behavior_record (session_id, task_id, executed_layer,
               behavior_type, count, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(r.session_id, r.task_id, r.executed_layer,
              r.behavior_type, r.count, r.timestamp) for r in records],
        )
        self.conn.commit()

    async def get_summary_by_session(self, session_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            """SELECT behavior_type, SUM(count) as total
               FROM behavior_record WHERE session_id = ?
               GROUP BY behavior_type""",
            (session_id,),
        ).fetchall()
        return {r["behavior_type"]: r["total"] for r in rows}
