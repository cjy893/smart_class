import asyncio
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class SystemMetricsProvider:
    queue_depth = 0

    def snapshot(self) -> dict[str, float]:
        memory_mb = 0
        cpu_percent = 0
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=None)
            memory_mb = int(psutil.virtual_memory().used / (1024 * 1024))
        except ImportError:
            pass
        return {
            "cpu_percent": cpu_percent,
            "gpu_percent": 0,
            "memory_mb": memory_mb,
        }


class StatusReporter:
    def __init__(self, cloud_id: str, mqtt, metrics_provider=None,
                 interval_seconds: int = 30, task_queue=None):
        self.cloud_id = cloud_id
        self.mqtt = mqtt
        self.metrics_provider = metrics_provider or SystemMetricsProvider()
        self.interval_seconds = interval_seconds
        self.task_queue = task_queue
        self._running = False
        self._task: asyncio.Task | None = None

    async def publish_once(self) -> None:
        try:
            load = self.metrics_provider.snapshot()
            status = "online"
        except Exception as exc:
            logger.warning("metrics collection failed: %s", exc)
            load = {"cpu_percent": 0, "gpu_percent": 0, "memory_mb": 0}
            status = "degraded"

        payload = {
            "cloud_id": self.cloud_id,
            "timestamp": datetime.utcnow().replace(microsecond=0).isoformat(),
            "load": load,
            "task_queue_depth": self._queue_depth(),
            "status": status,
        }
        await self.mqtt.publish("cloud/status/report", json.dumps(payload), qos=0)

    def _queue_depth(self) -> int:
        if self.task_queue and hasattr(self.task_queue, "get_queue_depth"):
            return int(self.task_queue.get_queue_depth())
        return int(getattr(self.metrics_provider, "queue_depth", 0))

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while self._running:
            await self.publish_once()
            await asyncio.sleep(self.interval_seconds)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
