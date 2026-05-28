import asyncio
from concurrent import futures
from pathlib import Path
from typing import Any

import edge_report_pb2
import edge_report_pb2_grpc


class InvalidReportError(ValueError):
    pass


class GrpcRuntimeAdapter:
    async def start(self, server: "GrpcServer") -> None:
        try:
            import grpc
        except ImportError as exc:
            raise RuntimeError("grpcio is required to run the cloud gRPC server") from exc
        runtime = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        edge_report_pb2_grpc.add_EdgeReportServicer_to_server(
            _EdgeReportServicer(server),
            runtime,
        )
        runtime.add_insecure_port(server.listen_address)
        runtime.start()
        server._runtime = runtime

    async def stop(self, server: "GrpcServer") -> None:
        if server._runtime is not None:
            await asyncio.to_thread(lambda: server._runtime.stop(0).wait())
            server._runtime = None


class GrpcServer:
    def __init__(self, listen_address: str = "0.0.0.0:50051", adapter=None):
        self.listen_address = listen_address
        self.adapter = adapter or GrpcRuntimeAdapter()
        self.latest_edge_status: dict[str, dict[str, Any]] = {}
        self.latest_heartbeats: dict[str, dict[str, Any]] = {}
        self.running = False
        self._runtime = None

    async def start(self) -> None:
        await self.adapter.start(self)
        self.running = True

    async def stop(self) -> None:
        await self.adapter.stop(self)
        self.running = False

    async def report_status(self, request: dict[str, Any]) -> dict[str, bool]:
        self._record_status(request)
        return {"ok": True}

    async def heartbeat(self, request: dict[str, Any]) -> dict[str, bool]:
        self._record_heartbeat(request)
        return {"ok": True}

    def _record_status(self, request: dict[str, Any]) -> None:
        edge_id = request.get("edge_id")
        if not edge_id:
            raise InvalidReportError("edge_id is required")
        self.latest_edge_status[edge_id] = dict(request)

    def _record_heartbeat(self, request: dict[str, Any]) -> None:
        edge_id = request.get("edge_id")
        if not edge_id:
            raise InvalidReportError("edge_id is required")
        self.latest_heartbeats[edge_id] = dict(request)

    @staticmethod
    def proto_path() -> Path:
        return Path(__file__).resolve().parents[1] / "proto" / "edge_report.proto"


class _EdgeReportServicer(edge_report_pb2_grpc.EdgeReportServicer):
    def __init__(self, server: GrpcServer):
        self.server = server

    def ReportStatus(self, request, context):
        self.server._record_status(_message_to_dict(request))
        return edge_report_pb2.Ack(ok=True)

    def Heartbeat(self, request, context):
        self.server._record_heartbeat(_message_to_dict(request))
        return edge_report_pb2.Ack(ok=True)


def _message_to_dict(message) -> dict[str, Any]:
    return {field.name: getattr(message, field.name) for field in message.DESCRIPTOR.fields}
