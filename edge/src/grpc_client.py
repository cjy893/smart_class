import asyncio
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


class GrpcClient:
    """gRPC 客户端：每 30s 向云端上报 StatusReport + Heartbeat。

    proto 定义: cloud/proto/edge_report.proto
    stub: edge/src/proto/edge_report_pb2_grpc.py
    """

    def __init__(self, cloud_address: str, edge_id: str):
        self.cloud_address = cloud_address
        self.edge_id = edge_id
        self._running = False
        self._stub = None
        self._channel = None

    async def start(self, interval_seconds: int = 30) -> None:
        self._running = True
        logger.info("GrpcClient started, reporting to %s every %ds",
                     self.cloud_address, interval_seconds)

        while self._running:
            if self._stub is None:
                await self._connect_lazy()
            if self._stub:
                try:
                    await self._report()
                except Exception as e:
                    logger.warning("gRPC report failed: %s", e)
                    self._stub = None
            await asyncio.sleep(interval_seconds)

    async def stop(self) -> None:
        self._running = False
        if self._channel:
            await asyncio.to_thread(self._channel.close)

    async def _connect_lazy(self) -> None:
        import grpc
        from proto import edge_report_pb2_grpc
        try:
            self._channel = grpc.aio.insecure_channel(self.cloud_address)
            self._stub = edge_report_pb2_grpc.EdgeReportStub(self._channel)
            logger.info("gRPC connected to %s", self.cloud_address)
        except Exception as e:
            logger.warning("gRPC connect failed: %s", e)

    async def _report(self) -> None:
        from proto import edge_report_pb2

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        report = edge_report_pb2.StatusReport(
            edge_id=self.edge_id,
            cpu_percent=_get_cpu_percent(),
            npu_percent=_get_npu_percent(),
            memory_mb=_get_memory_mb(),
            task_queue_depth=0,
            connected_devices=_count_connected_devices(),
            timestamp=now,
        )
        await self._stub.ReportStatus(report)

        hb = edge_report_pb2.HeartbeatRequest(
            edge_id=self.edge_id,
            timestamp=now,
        )
        await self._stub.Heartbeat(hb)
        logger.debug("gRPC: StatusReport + Heartbeat sent")


# ── System stats helpers ────────────────────────────────────────────────

def _get_cpu_percent() -> float:
    try:
        with open("/proc/stat") as f:
            fields = f.readline().split()
            total = sum(int(x) for x in fields[1:])
            idle = int(fields[4])
            return round((1 - idle / total) * 100, 1) if total > 0 else 0.0
    except Exception:
        return 0.0


def _get_npu_percent() -> float:
    try:
        out = os.popen("npu-smi info -t usge -i 0 2>/dev/null").read().strip()
        if out:
            return float(out)
    except Exception:
        pass
    return 0.0


def _get_memory_mb() -> float:
    try:
        meminfo = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    meminfo[key] = int(val)
        total = meminfo.get("MemTotal", 0)
        free = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        buffers = meminfo.get("Buffers", 0)
        cached = meminfo.get("Cached", 0)
        used = total - free - buffers - cached
        return round(max(used, 0) / 1024.0, 1)
    except Exception:
        return 0.0


def _count_connected_devices() -> int:
    try:
        out = os.popen(
            "ss -tn state established '( dport = :1883 )' 2>/dev/null | tail -n +2 | wc -l"
        ).read().strip()
        return int(out)
    except Exception:
        return 0
