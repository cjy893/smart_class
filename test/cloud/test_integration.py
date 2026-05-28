import asyncio
import base64
import json

from fakes import FakeBehaviorEngine, FakeMqttClient
from report.generator import ReportGenerator
from task_handler import CloudTaskHandler


def run(coro):
    return asyncio.run(coro)


def test_cloud_task_behavior_analyze_end_to_end_with_fakes():
    mqtt = FakeMqttClient()
    handler = CloudTaskHandler(mqtt, FakeBehaviorEngine(), ReportGenerator("/tmp"))
    payload = {
        "task_id": "behavior-1",
        "task_type": "behavior_analyze",
        "trigger_source": "user_button",
        "session_id": "classroom-301_2026-05-26_08-00",
        "device_id": "classroom-301",
        "created_at": "2026-05-26T08:15:02.123",
        "image": base64.b64encode(b"image-bytes").decode("ascii"),
        "params": {},
    }

    run(handler.handle_message("cloud/task/request/classroom-301", json.dumps(payload)))

    topic, message, qos = mqtt.published[0]
    assert topic == "cloud/task/result/classroom-301"
    assert qos == 1
    assert message["status"] == "COMPLETED"
    assert message["result"]["total_detected"] == 2


def test_cloud_task_report_generate_end_to_end_with_temp_reports_dir(tmp_path):
    mqtt = FakeMqttClient()
    handler = CloudTaskHandler(mqtt, FakeBehaviorEngine(), ReportGenerator(tmp_path))
    payload = {
        "task_id": "report-1",
        "task_type": "report_generate",
        "trigger_source": "system_timer",
        "session_id": "classroom-301_2026-05-26_08-00",
        "device_id": "classroom-301",
        "created_at": "2026-05-26T09:40:00",
        "image": "",
        "params": {
            "report_type": "final",
            "aggregate": {"person_count": {"avg": 31}},
        },
    }

    run(handler.handle_message("cloud/task/request/classroom-301", json.dumps(payload)))

    message = mqtt.published[0][1]
    assert message["status"] == "COMPLETED"
    assert (tmp_path / message["result"]["html_filename"]).exists()
    assert (tmp_path / message["result"]["json_filename"]).exists()


def test_duplicate_qos1_task_id_is_idempotent(tmp_path):
    mqtt = FakeMqttClient()
    behavior = FakeBehaviorEngine()
    handler = CloudTaskHandler(mqtt, behavior, ReportGenerator(tmp_path))
    payload = {
        "task_id": "behavior-1",
        "task_type": "behavior_analyze",
        "trigger_source": "user_button",
        "session_id": "classroom-301_2026-05-26_08-00",
        "device_id": "classroom-301",
        "created_at": "2026-05-26T08:15:02.123",
        "image": base64.b64encode(b"image-bytes").decode("ascii"),
        "params": {},
    }

    run(handler.handle_message("cloud/task/request/classroom-301", json.dumps(payload)))
    run(handler.handle_message("cloud/task/request/classroom-301", json.dumps(payload)))

    assert len(behavior.calls) == 1
    assert len(mqtt.published) == 2
    assert mqtt.published[0][1] == mqtt.published[1][1]
