import asyncio

from fakes import FakeMetricsProvider, FakeMqttClient
from status_reporter import StatusReporter


def run(coro):
    return asyncio.run(coro)


def test_status_reporter_publishes_documented_payload():
    mqtt = FakeMqttClient()
    reporter = StatusReporter("cloud-main", mqtt, FakeMetricsProvider())

    run(reporter.publish_once())

    topic, payload, qos = mqtt.published[0]
    assert topic == "cloud/status/report"
    assert qos == 0
    assert payload["cloud_id"] == "cloud-main"
    assert payload["timestamp"]
    assert payload["load"] == {
        "cpu_percent": 55.0,
        "gpu_percent": 40.0,
        "memory_mb": 4096,
    }
    assert payload["task_queue_depth"] == 3
    assert payload["status"] == "online"


def test_status_reporter_uses_handler_queue_depth_when_available():
    class Metrics(FakeMetricsProvider):
        queue_depth = 1

    class Handler:
        def get_queue_depth(self):
            return 5

    mqtt = FakeMqttClient()
    reporter = StatusReporter("cloud-main", mqtt, Metrics(), task_queue=Handler())

    run(reporter.publish_once())

    assert mqtt.published[0][1]["task_queue_depth"] == 5


def test_status_reporter_uses_configured_interval():
    mqtt = FakeMqttClient()
    reporter = StatusReporter("cloud-main", mqtt, FakeMetricsProvider(), interval_seconds=7)

    assert reporter.interval_seconds == 7


def test_status_reporter_start_returns_after_launching_background_loop():
    mqtt = FakeMqttClient()
    reporter = StatusReporter("cloud-main", mqtt, FakeMetricsProvider(), interval_seconds=60)

    async def scenario():
        await reporter.start()
        assert reporter._task is not None
        await reporter.stop()

    run(scenario())


def test_status_reporter_survives_metrics_collection_failure():
    class BrokenMetrics:
        queue_depth = 0

        def snapshot(self):
            raise RuntimeError("metrics unavailable")

    mqtt = FakeMqttClient()
    reporter = StatusReporter("cloud-main", mqtt, BrokenMetrics())

    run(reporter.publish_once())

    payload = mqtt.published[0][1]
    assert payload["status"] == "degraded"
    assert payload["load"] == {"cpu_percent": 0, "gpu_percent": 0, "memory_mb": 0}
