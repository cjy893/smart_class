from pathlib import Path

from report.generator import ReportGenerator


def report_payload(session_id="classroom-301_2026-05-26_08-00", report_type="final"):
    return {
        "task_id": "task-report-1",
        "task_type": "report_generate",
        "trigger_source": "system_timer" if report_type == "final" else "user_button",
        "session_id": session_id,
        "device_id": "classroom-301",
        "created_at": "2026-05-26T09:40:00",
        "params": {
            "report_type": report_type,
            "aggregate": {
                "person_count": {"avg": 31, "max": 36, "min": 28, "samples": 12},
                "attendance": {
                    "present": ["张三"],
                    "absent": ["李四"],
                    "unknown": 1,
                },
                "behavior": {
                    "hand_up": 4,
                    "standing": 1,
                    "head_down": 3,
                    "talking": 2,
                },
            },
        },
    }


def test_report_generator_writes_json_and_html_files(tmp_path):
    generator = ReportGenerator(tmp_path)

    result = generator.generate(report_payload())

    json_path = tmp_path / result["json_filename"]
    html_path = tmp_path / result["html_filename"]
    assert json_path.exists()
    assert html_path.exists()
    assert "classroom-301" in html_path.read_text(encoding="utf-8")


def test_report_generator_returns_report_url_and_summary(tmp_path):
    generator = ReportGenerator(tmp_path, public_url_prefix="/reports")

    result = generator.generate(report_payload())

    assert result["report_url"].startswith("/reports/")
    assert result["summary"] == {
        "avg_count": 31,
        "max_count": 36,
        "min_count": 28,
        "present": 1,
        "absent": 1,
        "unknown": 1,
        "behavior_events": 10,
    }
    assert result["session_id"] == "classroom-301_2026-05-26_08-00"
    assert result["task_id"] == "task-report-1"


def test_report_generator_supports_midterm_and_final_report(tmp_path):
    generator = ReportGenerator(tmp_path)

    midterm = generator.generate(report_payload(report_type="midterm"))
    final = generator.generate(report_payload(report_type="final"))

    assert midterm["report_type"] == "midterm"
    assert final["report_type"] == "final"
    assert "中期" in Path(tmp_path / midterm["html_filename"]).read_text(encoding="utf-8")
    assert "最终" in Path(tmp_path / final["html_filename"]).read_text(encoding="utf-8")


def test_report_generator_handles_empty_class_data(tmp_path):
    generator = ReportGenerator(tmp_path)
    payload = report_payload()
    payload["params"]["aggregate"] = {}

    result = generator.generate(payload)

    assert result["summary"] == {
        "avg_count": 0,
        "max_count": 0,
        "min_count": 0,
        "present": 0,
        "absent": 0,
        "unknown": 0,
        "behavior_events": 0,
    }


def test_report_generator_sanitizes_filename_from_session_id(tmp_path):
    generator = ReportGenerator(tmp_path)

    result = generator.generate(report_payload(session_id="../bad/session"))

    assert "/" not in result["html_filename"]
    assert ".." not in result["html_filename"]
    assert (tmp_path / result["html_filename"]).resolve().parent == tmp_path.resolve()
