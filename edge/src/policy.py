from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from db.models import Task


@dataclass
class SchedulingContext:
    edge_load: float = 0.0       # 0-100
    cloud_load: float = 0.0      # 0-100
    edge_queue_depth: int = 0
    cloud_queue_depth: int = 0
    edge_cloud_rtt_ms: float = 0.0
    device_edge_rtt_ms: float = 0.0


class Policy(ABC):
    @abstractmethod
    def decide(self, task: Task, context: SchedulingContext) -> str:
        """返回 'edge' 或 'cloud'."""
        ...


class GreedyNearbyPolicy(Policy):
    """能边不云。"""
    def decide(self, task: Task, context: SchedulingContext) -> str:
        return "edge"


class LoadBalancePolicy(Policy):
    """每层维护能力分数，选最空闲。"""
    def decide(self, task: Task, context: SchedulingContext) -> str:
        edge_score = max(0, 100 - context.edge_load - context.edge_queue_depth * 10)
        cloud_score = max(0, 100 - context.cloud_load - context.cloud_queue_depth * 10)
        return "edge" if edge_score >= cloud_score else "cloud"


class AdaptivePolicy(Policy):
    """0.5*延迟 + 0.3*精度 + 0.2*负载 加权打分。

    延迟: RTT 越低越好。边侧 RTT 取 device_edge_rtt，云端取 device_edge_rtt + edge_cloud_rtt。
    精度: 边侧给固定分 80，云端给固定分 100（默认云更精确）。
    负载: 负载越低越好。
    """

    def decide(self, task: Task, context: SchedulingContext) -> str:
        # 负载分数 (越低越好: 100 - load)
        edge_load_score = max(0, 100 - context.edge_load - context.edge_queue_depth * 10)
        cloud_load_score = max(0, 100 - context.cloud_load - context.cloud_queue_depth * 10)

        # 延迟分数 (越低越好: 归一化为 0-100, 假设最大 200ms)
        max_rtt = 200.0
        edge_lat = max(0, max_rtt - context.device_edge_rtt_ms) / max_rtt * 100
        cloud_lat = max(0, max_rtt - (context.device_edge_rtt_ms + context.edge_cloud_rtt_ms)) / max_rtt * 100

        # 精度分数
        edge_acc = 80.0
        cloud_acc = 100.0

        edge_total = 0.5 * edge_lat + 0.3 * edge_acc + 0.2 * edge_load_score
        cloud_total = 0.5 * cloud_lat + 0.3 * cloud_acc + 0.2 * cloud_load_score

        return "edge" if edge_total >= cloud_total else "cloud"
