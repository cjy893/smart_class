import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class GrpcClient:
    """gRPC 客户端，向云端上报状态和心跳。

    依赖 grpcio + 生成的 proto stub。
    proto 文件位于项目根目录 proto/edge_report.proto。
    首期用 MQTT 上报替代，gRPC 为后续扩展预留。
    """

    def __init__(self, cloud_address: str, edge_id: str):
        self.cloud_address = cloud_address
        self.edge_id = edge_id
        self._running = False
        self._stub = None

    async def start(self, interval_seconds: int = 30) -> None:
        self._running = True
        logger.info("GrpcClient started, reporting to %s every %ds",
                     self.cloud_address, interval_seconds)
        while self._running:
            try:
                await self._report()
            except Exception as e:
                logger.warning("gRPC report failed: %s", e)
            await asyncio.sleep(interval_seconds)

    async def stop(self) -> None:
        self._running = False

    async def _report(self) -> None:
        """发送 StatusReport 到云端。

        首期使用 MQTT 上报替代（更简单的运维部署），
        gRPC 通道预留，后续通过 proto stub 替换实现。
        """
        # 预留：通过 MQTT fallback 实现
        # await self._stub.ReportStatus(StatusReport(...))
        pass

    async def heartbeat(self) -> None:
        """发送心跳到云端。"""
        pass
