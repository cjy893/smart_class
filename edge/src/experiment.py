import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from db.models import Task
from policy import AdaptivePolicy, GreedyNearbyPolicy, LoadBalancePolicy, SchedulingContext
from scheduler import Scheduler

logger = logging.getLogger(__name__)


class Experiment:
    """实验模式：依次用三种策略发送 N 个模拟任务，统计 CDF 数据。

    管理员在 Dashboard 触发。实验期间不阻塞真实任务。
    """

    def __init__(self, scheduler: Scheduler,
                 test_images_dir: str,
                 simulated_task_count: int = 100):
        self.scheduler = scheduler
        self.test_images_dir = Path(test_images_dir)
        self.simulated_task_count = simulated_task_count
        self._running = False
        self.results: dict[str, dict] = {}  # policy_name → {latencies: [...], path: [...]}

    async def run(self) -> dict:
        """运行实验：三策略各发 N 个模拟任务。"""
        self._running = True
        self.results.clear()

        policies = [
            ("greedy_nearby", GreedyNearbyPolicy()),
            ("load_balance", LoadBalancePolicy()),
            ("adaptive", AdaptivePolicy()),
        ]

        images = self._load_test_images()
        if not images:
            logger.error("No test images found in %s", self.test_images_dir)
            return {}

        for name, policy in policies:
            logger.info("Experiment: testing policy=%s, N=%d", name, self.simulated_task_count)
            latencies = []
            paths = []

            for i in range(min(self.simulated_task_count, len(images))):
                ctx = self.scheduler.context
                task = Task(
                    task_id=f"exp_{name}_{i}",
                    task_type="behavior_analyze",
                    trigger_source="dashboard_manual",
                    session_id="experiment",
                    device_id="experiment",
                    created_at="",
                )

                t0 = time.perf_counter()
                target = policy.decide(task, ctx)
                t1 = time.perf_counter()

                latencies.append((t1 - t0) * 1000)
                paths.append(target)

            latencies.sort()
            self.results[name] = {
                "latencies_ms": latencies,
                "paths": paths,
                "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
                "edge_ratio": paths.count("edge") / len(paths) if paths else 0,
            }

        self._running = False
        return self.results

    def _load_test_images(self) -> list[bytes]:
        images = []
        if not self.test_images_dir.exists():
            return images
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            for f in sorted(self.test_images_dir.glob(ext)):
                images.append(f.read_bytes())
        return images

    def is_running(self) -> bool:
        return self._running
