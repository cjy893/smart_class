import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class ReportGenerator:
    def __init__(self, reports_dir: str | Path, public_url_prefix: str = "/reports"):
        self.reports_dir = Path(reports_dir)
        self.public_url_prefix = public_url_prefix.rstrip("/")
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        params = payload.get("params") or {}
        aggregate = params.get("aggregate") or {}
        report_type = params.get("report_type") or _infer_report_type(payload)
        summary = _summary(aggregate)

        task_id = payload.get("task_id", "")
        session_id = payload.get("session_id", "")
        stem = _safe_filename(f"{session_id}_{task_id}_{report_type}") or "report"
        json_filename = f"{stem}.json"
        html_filename = f"{stem}.html"

        report_doc = {
            "task_id": task_id,
            "session_id": session_id,
            "device_id": payload.get("device_id", ""),
            "report_type": report_type,
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "summary": summary,
            "aggregate": aggregate,
        }

        json_path = self.reports_dir / json_filename
        html_path = self.reports_dir / html_filename
        json_path.write_text(
            json.dumps(report_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        html_path.write_text(_render_html(report_doc), encoding="utf-8")

        return {
            "task_id": task_id,
            "session_id": session_id,
            "report_type": report_type,
            "summary": summary,
            "json_filename": json_filename,
            "html_filename": html_filename,
            "report_url": f"{self.public_url_prefix}/{html_filename}",
        }


def _infer_report_type(payload: dict[str, Any]) -> str:
    return "final" if payload.get("trigger_source") == "system_timer" else "midterm"


def _summary(aggregate: dict[str, Any]) -> dict[str, int | float]:
    person_count = aggregate.get("person_count") or {}
    attendance = aggregate.get("attendance") or {}
    behavior = aggregate.get("behavior") or {}
    behavior_events = sum(int(behavior.get(key, 0) or 0)
                          for key in ("hand_up", "standing", "head_down", "talking"))

    return {
        "avg_count": person_count.get("avg", 0) or 0,
        "max_count": person_count.get("max", 0) or 0,
        "min_count": person_count.get("min", 0) or 0,
        "present": len(attendance.get("present") or []),
        "absent": len(attendance.get("absent") or []),
        "unknown": int(attendance.get("unknown", 0) or 0),
        "behavior_events": behavior_events,
    }


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    cleaned = cleaned.replace("..", "_").strip("._")
    return cleaned[:180]


def _render_html(report_doc: dict[str, Any]) -> str:
    title_label = "最终" if report_doc["report_type"] == "final" else "中期"
    session_id = html.escape(str(report_doc["session_id"]))
    device_id = html.escape(str(report_doc["device_id"]))
    summary = report_doc["summary"]
    rows = "\n".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in summary.items()
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{title_label}课堂报告 - {session_id}</title>
</head>
<body>
  <h1>{title_label}课堂报告</h1>
  <p>Session: {session_id}</p>
  <p>Device: {device_id}</p>
  <table>
    <tbody>
      {rows}
    </tbody>
  </table>
</body>
</html>
"""
