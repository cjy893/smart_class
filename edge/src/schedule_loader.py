import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

ScheduleCallback = Callable[[dict], Awaitable[None]]


class ScheduleLoader:
    """加载课表 JSON，每分钟检查上课/下课时间，触发回调。"""

    def __init__(self, schedule_path: str):
        self.schedule_path = Path(schedule_path)
        self._entries: list[dict] = []
        self._on_class_start: Optional[ScheduleCallback] = None
        self._on_class_end: Optional[ScheduleCallback] = None
        self._active_sessions: set[str] = set()  # {device_id}_{date}_{start_time}
        self._running = False

    def on_class_start(self, cb: ScheduleCallback) -> None:
        self._on_class_start = cb

    def on_class_end(self, cb: ScheduleCallback) -> None:
        self._on_class_end = cb

    def load(self) -> list[dict]:
        raw = json.loads(self.schedule_path.read_text())
        self._entries = raw.get("schedule", [])
        logger.info("Schedule loaded: %d entries", len(self._entries))
        return self._entries

    def reload(self) -> list[dict]:
        return self.load()

    def get_entries(self) -> list[dict]:
        return self._entries

    def is_class_time(self, device_id: str) -> bool:
        now = datetime.now()
        today_weekday = now.isoweekday()
        current_time = now.strftime("%H:%M")
        for entry in self._entries:
            if entry.get("device_id") != device_id:
                continue
            if entry.get("day_of_week") != today_weekday:
                continue
            if entry["start_time"] <= current_time < entry["end_time"]:
                return True
        return False

    async def start(self) -> None:
        """每分钟检查一次，触发 class_start / class_end 回调。"""
        self._running = True
        # 初始化时标记当前已在上课中的 session（防止重启后重复触发 start）
        self._init_active_sessions()
        logger.info("ScheduleLoader started, active sessions: %d", len(self._active_sessions))
        while self._running:
            await self._tick()
            await asyncio.sleep(60)

    def stop(self) -> None:
        self._running = False

    def _init_active_sessions(self) -> None:
        now = datetime.now()
        today_weekday = now.isoweekday()
        current_time = now.strftime("%H:%M")
        for entry in self._entries:
            if entry.get("day_of_week") != today_weekday:
                continue
            if entry["start_time"] <= current_time < entry["end_time"]:
                sid = self._make_session_id(entry)
                self._active_sessions.add(sid)

    def _make_session_id(self, entry: dict) -> str:
        date_str = datetime.now().strftime("%Y-%m-%d")
        return f"{entry['device_id']}_{date_str}_{entry['start_time']}"

    async def _tick(self) -> None:
        now = datetime.now()
        today_weekday = now.isoweekday()
        current_time = now.strftime("%H:%M")

        for entry in self._entries:
            if entry.get("day_of_week") != today_weekday:
                continue
            sid = self._make_session_id(entry)

            # 上课触发
            if current_time == entry["start_time"] and sid not in self._active_sessions:
                self._active_sessions.add(sid)
                logger.info("Class start: %s", sid)
                if self._on_class_start:
                    await self._on_class_start(entry)

            # 下课触发
            if current_time == entry["end_time"] and sid in self._active_sessions:
                self._active_sessions.discard(sid)
                logger.info("Class end: %s", sid)
                if self._on_class_end:
                    await self._on_class_end(entry)
