import logging
from datetime import datetime
from typing import Optional

from db.models import Session
from db.repository import SessionRepository, PersonCountRepository
from mqtt_client import MqttClient

logger = logging.getLogger(__name__)


class SessionManager:
    """课堂生命周期管理。"""

    def __init__(self, session_repo: SessionRepository,
                 pc_repo: PersonCountRepository,
                 mqtt: Optional[MqttClient] = None):
        self.session_repo = session_repo
        self.pc_repo = pc_repo
        self.mqtt = mqtt
        self._active_sessions: dict[str, Session] = {}  # device_id → Session

    async def start_session(self, schedule_entry: dict) -> Session:
        device_id = schedule_entry["device_id"]
        date_str = datetime.now().strftime("%Y-%m-%d")
        start_time = schedule_entry["start_time"]
        session_id = f"{device_id}_{date_str}_{start_time}"

        existing = await self.session_repo.get_active(device_id)
        if existing and existing.session_id == session_id:
            logger.info("Session already active: %s", session_id)
            self._active_sessions[device_id] = existing
            return existing

        s = Session(
            session_id=session_id,
            device_id=device_id,
            course_name=schedule_entry.get("course_name"),
            teacher=schedule_entry.get("teacher"),
            class_name=schedule_entry.get("class_name"),
            start_time=f"{date_str}T{start_time}:00",
            status="active",
        )
        await self.session_repo.create(s)
        self._active_sessions[device_id] = s

        # 通知端侧 session 开始
        if self.mqtt:
            cmd = (
                '{"command":"session_restore",'
                f'"session_id":"{session_id}",'
                '"policy":"adaptive"}'
            )
            await self.mqtt.publish(f"edge/schedule/command/{device_id}", cmd, qos=1)

        logger.info("Session started: %s", session_id)
        return s

    async def end_session(self, session_id: str) -> Optional[Session]:
        s = await self.session_repo.get(session_id)
        if not s:
            logger.warning("Session not found: %s", session_id)
            return None

        ended_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        await self.session_repo.end(session_id, ended_at)
        self._active_sessions.pop(s.device_id, None)

        # 聚合 person_count 数据
        await self.pc_repo.aggregate_and_prune(session_id)

        logger.info("Session ended: %s", session_id)
        return s

    async def get_active_session(self, device_id: str) -> Optional[Session]:
        if device_id in self._active_sessions:
            return self._active_sessions[device_id]
        s = await self.session_repo.get_active(device_id)
        if s:
            self._active_sessions[device_id] = s
        return s

    async def recover_active_sessions(self) -> list[Session]:
        """重启恢复：查出所有活跃 session。"""
        sessions = await self.session_repo.list_active()
        for s in sessions:
            self._active_sessions[s.device_id] = s
            logger.info("Recovered active session: %s (device=%s)", s.session_id, s.device_id)
        return sessions

    def is_class_time(self, device_id: str) -> bool:
        return device_id in self._active_sessions
