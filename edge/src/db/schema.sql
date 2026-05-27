-- Session: 课堂记录
CREATE TABLE IF NOT EXISTS session (
    session_id   TEXT PRIMARY KEY,
    device_id    TEXT NOT NULL,
    course_name  TEXT,
    teacher      TEXT,
    class_name   TEXT,
    start_time   TEXT NOT NULL,
    ended_at     TEXT,
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Task: 任务记录 (person_count 不入此表)
CREATE TABLE IF NOT EXISTS task (
    task_id        TEXT PRIMARY KEY,
    task_type      TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    session_id     TEXT NOT NULL REFERENCES session(session_id),
    device_id      TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'CREATED',
    target_layer   TEXT,
    result_json    TEXT,
    metrics_json   TEXT,
    created_at     TEXT NOT NULL,
    completed_at   TEXT,
    timeout_at     TEXT,
    attempt        INTEGER DEFAULT 1
);

-- PersonCount: 人数统计采样点
CREATE TABLE IF NOT EXISTS person_count (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES session(session_id),
    device_id   TEXT NOT NULL,
    count       INTEGER NOT NULL,
    timestamp   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_person_count_session ON person_count(session_id, timestamp);

-- PersonCountAgg: 每课聚合摘要
CREATE TABLE IF NOT EXISTS person_count_aggregate (
    session_id    TEXT PRIMARY KEY REFERENCES session(session_id),
    avg_count     REAL,
    max_count     INTEGER,
    min_count     INTEGER,
    sample_count  INTEGER,
    aggregated_at TEXT NOT NULL
);

-- AttendanceRecord: 签到明细
CREATE TABLE IF NOT EXISTS attendance_record (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES session(session_id),
    task_id      TEXT NOT NULL REFERENCES task(task_id),
    student_id   TEXT NOT NULL,
    student_name TEXT NOT NULL,
    status       TEXT NOT NULL,
    confidence   REAL,
    timestamp    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attendance_session ON attendance_record(session_id);

-- BehaviorRecord: 行为分析结果
CREATE TABLE IF NOT EXISTS behavior_record (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL REFERENCES session(session_id),
    task_id        TEXT NOT NULL REFERENCES task(task_id),
    executed_layer TEXT NOT NULL,
    behavior_type  TEXT NOT NULL,
    count          INTEGER NOT NULL,
    timestamp      TEXT NOT NULL
);
