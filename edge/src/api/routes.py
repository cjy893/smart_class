import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from api.sse import SseManager
from db.repository import (
    AttendanceRepository, BehaviorRepository,
    PersonCountRepository, SessionRepository,
)

logger = logging.getLogger(__name__)


def create_router(
    session_repo: SessionRepository,
    person_count_repo: PersonCountRepository,
    attendance_repo: AttendanceRepository,
    behavior_repo: BehaviorRepository,
    sse_mgr: SseManager,
    scheduler=None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/nodes/status")
    async def nodes_status():
        """三级节点在线状态 + CPU/NPU/队列。"""
        return JSONResponse({
            "nodes": [],
            "updated_at": datetime.now().isoformat(),
        })

    @router.get("/api/v1/network/rtt")
    async def network_rtt():
        return JSONResponse({
            "device_edge_ms": 0,
            "edge_cloud_ms": 0,
        })

    @router.get("/api/v1/tasks/distribution")
    async def tasks_distribution():
        return JSONResponse({
            "device": 0, "edge": 0, "cloud": 0,
        })

    @router.get("/api/v1/tasks/timeline")
    async def tasks_timeline(limit: int = Query(20, ge=1, le=100)):
        return JSONResponse({"tasks": []})

    @router.get("/api/v1/performance/latency")
    async def performance_latency():
        return JSONResponse({
            "p50_ms": 0, "p95_ms": 0, "p99_ms": 0,
        })

    @router.get("/api/v1/performance/throughput")
    async def performance_throughput():
        return JSONResponse({"tasks_per_second": 0})

    @router.get("/api/v1/classroom/count-history")
    async def count_history(
        session_id: Optional[str] = Query(None),
        device_id: Optional[str] = Query(None),
    ):
        if not session_id and device_id:
            s = await session_repo.get_active(device_id)
            if s:
                session_id = s.session_id
        if not session_id:
            return JSONResponse({"data_points": [], "aggregate": None})

        is_active = bool(await session_repo.get_active(device_id or "") if device_id else False)
        if is_active:
            points = await person_count_repo.get_by_session(session_id)
            data = [{"count": p.count, "timestamp": p.timestamp} for p in points]
        else:
            agg = await person_count_repo.get_aggregate(session_id)
            data = []
            aggregate = None
            if agg:
                aggregate = {
                    "avg_count": agg.avg_count,
                    "max_count": agg.max_count,
                    "min_count": agg.min_count,
                    "sample_count": agg.sample_count,
                }
            return JSONResponse({"data_points": data, "aggregate": aggregate})

        return JSONResponse({"data_points": data, "aggregate": None})

    @router.get("/api/v1/classroom/attendance")
    async def classroom_attendance(
        session_id: Optional[str] = Query(None),
        device_id: Optional[str] = Query(None),
    ):
        if not session_id and device_id:
            s = await session_repo.get_active(device_id)
            if s:
                session_id = s.session_id
        if not session_id:
            return JSONResponse({"records": []})

        records = await attendance_repo.get_latest_by_session(session_id)
        return JSONResponse({
            "records": [
                {"student_id": r.student_id, "student_name": r.student_name,
                 "status": r.status, "timestamp": r.timestamp}
                for r in records
            ]
        })

    @router.get("/api/v1/classroom/behavior")
    async def classroom_behavior(
        session_id: Optional[str] = Query(None),
        device_id: Optional[str] = Query(None),
    ):
        if not session_id and device_id:
            s = await session_repo.get_active(device_id)
            if s:
                session_id = s.session_id
        if not session_id:
            return JSONResponse({"behaviors": {}})

        summary = await behavior_repo.get_summary_by_session(session_id)
        return JSONResponse({"behaviors": summary})

    @router.get("/api/v1/experiment/results")
    async def experiment_results():
        return JSONResponse({"results": {}, "running": False})

    @router.post("/api/v1/experiment/start")
    async def experiment_start():
        return JSONResponse({"status": "not_implemented"})

    return router
