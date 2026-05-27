import asyncio
import base64
import json

from fakes import FakeBehaviorEngine, FakeMqttClient, FakeReportGenerator
from task_handler import CloudTaskHandler


def run(coro):
    return asyncio.run(coro)


def sample_task(task_type="behavior_analyze"):
    payload = {
        "task_id": "task-1",
        "task_type": task_type,
        "trigger_source": "user_button",
        "session_id": "classroom-301_2026-05-26_08-00",
        "device_id": "classroom-301",
        "created_at": "2026-05-26T08:15:02.123",
        "image": base64.b64encode(b"fake-jpeg").decode("ascii"),
        "params": {},
    }
    if task_type == "report_generate":
        payload["params"] = {
            "report_type": "final",
            "aggregate": {"person_count": {"avg": 31}},
        }
        payload["image"] = ""
    return payload


def test_subscribes_to_cloud_task_request_on_start():
    mqtt = FakeMqttClient()
    handler = CloudTaskHandler(mqtt, FakeBehaviorEngine(), FakeReportGenerator())

    run(handler.start())

    assert mqtt.subscriptions == [("cloud/task/request/#", 1)]


def test_routes_behavior_analyze_task_to_behavior_engine():
    mqtt = FakeMqttClient()
    behavior = FakeBehaviorEngine()
    handler = CloudTaskHandler(mqtt, behavior, FakeReportGenerator())
    payload = sample_task("behavior_analyze")

    run(handler.handle_message("cloud/task/request/classroom-301", json.dumps(payload)))

    assert behavior.calls == [(b"fake-jpeg", {})]
    assert mqtt.published[0][0] == "cloud/task/result/classroom-301"
    assert mqtt.published[0][2] == 1
    result = mqtt.published[0][1]
    assert result["task_id"] == "task-1"
    assert result["task_type"] == "behavior_analyze"
    assert result["device_id"] == "classroom-301"
    assert result["status"] == "COMPLETED"
    assert result["result"]["hand_up"] == 1
    assert "inference_latency_ms" in result["metrics"]


def test_routes_report_generate_task_to_report_generator():
    mqtt = FakeMqttClient()
    report_generator = FakeReportGenerator()
    handler = CloudTaskHandler(mqtt, FakeBehaviorEngine(), report_generator)
    payload = sample_task("report_generate")

    run(handler.handle_message("cloud/task/request/classroom-301", json.dumps(payload)))

    assert report_generator.calls == [payload]
    topic, message, qos = mqtt.published[0]
    assert topic == "cloud/task/result/classroom-301"
    assert qos == 1
    assert message["status"] == "COMPLETED"
    assert message["result"]["report_url"] == "/reports/report.html"
    assert message["result"]["summary"]["avg_count"] == 31


def test_rejects_unknown_task_type():
    mqtt = FakeMqttClient()
    behavior = FakeBehaviorEngine()
    report_generator = FakeReportGenerator()
    handler = CloudTaskHandler(mqtt, behavior, report_generator)
    payload = sample_task("face_attendance")

    run(handler.handle_message("cloud/task/request/classroom-301", json.dumps(payload)))

    assert behavior.calls == []
    assert report_generator.calls == []
    message = mqtt.published[0][1]
    assert message["status"] == "REJECTED"
    assert "unsupported task_type" in message["error"]


def test_invalid_json_payload_publishes_failed_result_when_task_id_available():
    mqtt = FakeMqttClient()
    handler = CloudTaskHandler(mqtt, FakeBehaviorEngine(), FakeReportGenerator())
    payload = '{"task_id": "task-1", "device_id": "classroom-301",'

    run(handler.handle_message("cloud/task/request/classroom-301", payload))

    topic, message, qos = mqtt.published[0]
    assert topic == "cloud/task/result/classroom-301"
    assert qos == 1
    assert message["task_id"] == "task-1"
    assert message["device_id"] == "classroom-301"
    assert message["status"] == "FAILED"
    assert "invalid json" in message["error"]


def test_missing_required_task_fields_returns_failed_result():
    mqtt = FakeMqttClient()
    handler = CloudTaskHandler(mqtt, FakeBehaviorEngine(), FakeReportGenerator())
    payload = sample_task("behavior_analyze")
    del payload["session_id"]

    run(handler.handle_message("cloud/task/request/classroom-301", json.dumps(payload)))

    message = mqtt.published[0][1]
    assert message["status"] == "FAILED"
    assert "session_id" in message["error"]


def test_invalid_base64_behavior_image_returns_failed_result():
    mqtt = FakeMqttClient()
    behavior = FakeBehaviorEngine()
    handler = CloudTaskHandler(mqtt, behavior, FakeReportGenerator())
    payload = sample_task("behavior_analyze")
    payload["image"] = "not base64!"

    run(handler.handle_message("cloud/task/request/classroom-301", json.dumps(payload)))

    message = mqtt.published[0][1]
    assert behavior.calls == []
    assert message["status"] == "FAILED"
    assert "invalid base64 image" in message["error"]
