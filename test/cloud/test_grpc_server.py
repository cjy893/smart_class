import asyncio

import pytest

from grpc_server import GrpcServer, InvalidReportError


def run(coro):
    return asyncio.run(coro)


def status_report(edge_id="edge-main", timestamp="2026-05-26T08:15:02"):
    return {
        "edge_id": edge_id,
        "cpu_percent": 40.0,
        "npu_percent": 20.0,
        "memory_mb": 1024,
        "task_queue_depth": 2,
        "connected_devices": 1,
        "timestamp": timestamp,
    }


def test_report_status_returns_ack_ok():
    server = GrpcServer()

    ack = run(server.report_status(status_report()))

    assert ack == {"ok": True}


def test_heartbeat_returns_ack_ok():
    server = GrpcServer()

    ack = run(server.heartbeat({"edge_id": "edge-main", "timestamp": "2026-05-26T08:15:02"}))

    assert ack == {"ok": True}


def test_grpc_server_records_latest_edge_status():
    server = GrpcServer()

    run(server.report_status(status_report(timestamp="2026-05-26T08:15:02")))
    run(server.report_status(status_report(timestamp="2026-05-26T08:16:02")))

    assert server.latest_edge_status["edge-main"]["timestamp"] == "2026-05-26T08:16:02"


def test_grpc_rejects_missing_edge_id():
    server = GrpcServer()
    payload = status_report(edge_id="")

    with pytest.raises(InvalidReportError, match="edge_id"):
        run(server.report_status(payload))


def test_grpc_server_has_documented_service_definition():
    proto_path = GrpcServer.proto_path()

    text = proto_path.read_text(encoding="utf-8")
    assert "service EdgeReport" in text
    assert "rpc ReportStatus" in text
    assert "rpc Heartbeat" in text
    assert "message Ack" in text


def test_grpc_server_start_uses_runtime_adapter():
    class Adapter:
        def __init__(self):
            self.started = []
            self.stopped = []

        async def start(self, server):
            self.started.append(server.listen_address)

        async def stop(self, server):
            self.stopped.append(server.listen_address)

    adapter = Adapter()
    server = GrpcServer("127.0.0.1:50051", adapter=adapter)

    run(server.start())
    run(server.stop())

    assert adapter.started == ["127.0.0.1:50051"]
    assert adapter.stopped == ["127.0.0.1:50051"]
