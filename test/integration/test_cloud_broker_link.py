import asyncio
import base64
import importlib.util
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    import paho.mqtt.client as paho_mqtt
except ImportError:
    paho_mqtt = None

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
CLOUD_SRC = ROOT / "cloud" / "src"
EDGE_SRC = ROOT / "edge" / "src"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PahoProbe:
    def __init__(self, host, port, client_id):
        self.host = host
        self.port = port
        self.messages = queue.Queue()
        self.connected = False
        self.client = paho_mqtt.Client(client_id=client_id, protocol=paho_mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        self.connected = rc == 0

    def _on_message(self, client, userdata, msg):
        self.messages.put((msg.topic, msg.payload.decode("utf-8"), msg.qos))

    def connect(self):
        self.client.connect(self.host, self.port, keepalive=30)
        self.client.loop_start()
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.connected:
                return
            time.sleep(0.05)
        raise AssertionError("probe client did not connect to broker")

    def subscribe(self, topic, qos):
        result, _ = self.client.subscribe(topic, qos)
        assert result == 0
        time.sleep(0.2)

    def publish(self, topic, payload, qos):
        info = self.client.publish(topic, payload, qos=qos)
        info.wait_for_publish(timeout=3)
        assert info.is_published()

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()


class FakeBehaviorEngine:
    def __init__(self):
        self.calls = []

    async def analyze(self, image_bytes, params=None):
        self.calls.append((image_bytes, params or {}))
        return {
            "total_detected": 2,
            "hand_up": 1,
            "standing": 0,
            "head_down": 0,
            "talking": 1,
        }


class FakeReportGenerator:
    def generate(self, payload):
        return {
            "report_url": "/reports/session-1.html",
            "summary": {"avg_count": 30, "behavior_events": 2},
        }


class FakeMetricsProvider:
    queue_depth = 4

    def snapshot(self):
        return {
            "cpu_percent": 12.5,
            "gpu_percent": 0,
            "memory_mb": 256,
        }


def _client_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex}"


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("192.168.137.2", 0))
        return sock.getsockname()[1]


def _tcp_reachable(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


def _wait_for_tcp(host, port, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _tcp_reachable(host, port):
            return True
        time.sleep(0.05)
    return False


@pytest.fixture(scope="session")
def mqtt_runtime():
    if paho_mqtt is None:
        pytest.skip("paho-mqtt is required for MQTT broker integration tests")

    cloud_mqtt_module = _load_module(
        "smart_class_cloud_mqtt_client_integration",
        CLOUD_SRC / "mqtt_client.py",
    )
    edge_mqtt_module = _load_module(
        "smart_class_edge_mqtt_client_integration",
        EDGE_SRC / "mqtt_client.py",
    )
    cloud_task_module = _load_module(
        "smart_class_cloud_task_handler_integration",
        CLOUD_SRC / "task_handler.py",
    )
    status_reporter_module = _load_module(
        "smart_class_status_reporter_integration",
        CLOUD_SRC / "status_reporter.py",
    )
    return SimpleNamespace(
        CloudMqttClient=cloud_mqtt_module.MqttClient,
        EdgeMqttClient=edge_mqtt_module.MqttClient,
        CloudTaskHandler=cloud_task_module.CloudTaskHandler,
        StatusReporter=status_reporter_module.StatusReporter,
    )


@pytest.fixture(scope="session")
def broker_endpoint(mqtt_runtime, tmp_path_factory):
    host = os.environ.get("SMART_CLASS_MQTT_BROKER_HOST")
    port = int(os.environ.get("SMART_CLASS_MQTT_BROKER_PORT", "1883"))
    if host:
        if not _wait_for_tcp(host, port):
            pytest.skip(f"configured MQTT broker is not reachable: {host}:{port}")
        yield host, port
        return

    mosquitto = shutil.which("mosquitto")
    amqtt = shutil.which("amqtt")
    if not mosquitto and not amqtt:
        pytest.skip(
            "mosquitto/amqtt are not installed and SMART_CLASS_MQTT_BROKER_HOST is not set"
        )

    port = _find_free_port()
    if mosquitto:
        command = [mosquitto, "-p", str(port), "-v"]
    else:
        config_path = tmp_path_factory.mktemp("amqtt") / "broker.yaml"
        config_path.write_text(_amqtt_config(port), encoding="utf-8")
        command = [amqtt, "-c", str(config_path)]

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        if not _wait_for_tcp("192.168.137.2", port):
            output = ""
            if process.poll() is not None and process.stdout:
                output = process.stdout.read()
            pytest.skip(f"mosquitto did not start for integration tests: {output}")
        yield "192.168.137.2", port
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _amqtt_config(port):
    return textwrap.dedent(f"""\
        ---
        listeners:
          default:
            type: tcp
            bind: 192.168.137.2:{port}
        plugins:
          amqtt.plugins.authentication.AnonymousAuthPlugin:
            allow_anonymous: true
          amqtt.plugins.sys.broker.BrokerSysPlugin:
            sys_interval: 20
        """)


def _behavior_task_payload(task_id="behavior-link-1"):
    image = base64.b64encode(b"frame-bytes").decode("ascii")
    return {
        "task_id": task_id,
        "task_type": "behavior_analyze",
        "trigger_source": "user_button",
        "session_id": "session-1",
        "device_id": "classroom-301",
        "created_at": "2026-05-26T08:15:02",
        "image": image,
        "params": {"threshold": 0.4},
    }


async def _wait_for_connected(client):
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        if getattr(client, "_connected", False):
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"{client.client_id} did not connect to MQTT broker")


async def _connect_client(client):
    await client.connect()
    await _wait_for_connected(client)
    return client


async def _next_probe_message(probe, timeout=3):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            return probe.messages.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.05)
    raise AssertionError("timed out waiting for MQTT message")


def run(coro):
    return asyncio.run(coro)


def test_cloud_client_connects_and_receives_task_request(mqtt_runtime, broker_endpoint):
    async def scenario():
        host, port = broker_endpoint
        cloud = mqtt_runtime.CloudMqttClient(host, port, _client_id("cloud-link"))
        received = asyncio.Queue()

        async def handler(topic, payload):
            await received.put((topic, payload))

        probe = PahoProbe(host, port, _client_id("request-publisher"))
        try:
            await _connect_client(cloud)
            await cloud.subscribe("cloud/task/request/#", 1, handler)
            await asyncio.sleep(0.2)

            payload = json.dumps(_behavior_task_payload("link-connect-1"))
            probe.connect()
            probe.publish("cloud/task/request/classroom-301", payload, qos=1)
            topic, body = await asyncio.wait_for(received.get(), timeout=3)
        finally:
            probe.close()
            await cloud.disconnect()

        assert topic == "cloud/task/request/classroom-301"
        assert json.loads(body)["task_id"] == "link-connect-1"

    run(scenario())


def test_cloud_task_handler_round_trips_behavior_result(mqtt_runtime, broker_endpoint):
    async def scenario():
        host, port = broker_endpoint
        cloud = mqtt_runtime.CloudMqttClient(host, port, _client_id("cloud-handler"))
        behavior = FakeBehaviorEngine()
        handler = mqtt_runtime.CloudTaskHandler(cloud, behavior, FakeReportGenerator())
        result_probe = PahoProbe(host, port, _client_id("result-subscriber"))
        request_probe = PahoProbe(host, port, _client_id("request-publisher"))
        try:
            result_probe.connect()
            result_probe.subscribe("cloud/task/result/classroom-301", qos=1)
            await _connect_client(cloud)
            await handler.start()
            await asyncio.sleep(0.2)

            request_probe.connect()
            request_probe.publish(
                "cloud/task/request/classroom-301",
                json.dumps(_behavior_task_payload("round-trip-1")),
                qos=1,
            )
            topic, payload, qos = await _next_probe_message(result_probe)
        finally:
            request_probe.close()
            result_probe.close()
            await cloud.disconnect()

        body = json.loads(payload)
        assert topic == "cloud/task/result/classroom-301"
        assert qos == 1
        assert body["task_id"] == "round-trip-1"
        assert body["device_id"] == "classroom-301"
        assert body["session_id"] == "session-1"
        assert body["status"] == "COMPLETED"
        assert body["result"]["hand_up"] == 1
        assert behavior.calls == [(b"frame-bytes", {"threshold": 0.4})]

    run(scenario())


def test_cloud_status_report_reaches_broker(mqtt_runtime, broker_endpoint):
    async def scenario():
        host, port = broker_endpoint
        cloud = mqtt_runtime.CloudMqttClient(host, port, _client_id("cloud-status"))
        status_probe = PahoProbe(host, port, _client_id("status-subscriber"))
        try:
            status_probe.connect()
            status_probe.subscribe("cloud/status/report", qos=0)
            await _connect_client(cloud)
            reporter = mqtt_runtime.StatusReporter(
                "cloud-main",
                cloud,
                metrics_provider=FakeMetricsProvider(),
            )

            await reporter.publish_once()
            topic, payload, qos = await _next_probe_message(status_probe)
        finally:
            status_probe.close()
            await cloud.disconnect()

        body = json.loads(payload)
        assert topic == "cloud/status/report"
        assert qos == 0
        assert body["cloud_id"] == "cloud-main"
        assert body["status"] == "online"
        assert body["load"] == {
            "cpu_percent": 12.5,
            "gpu_percent": 0,
            "memory_mb": 256,
        }
        assert body["task_queue_depth"] == 4

    run(scenario())


def test_edge_cloud_edge_round_trip_through_broker(mqtt_runtime, broker_endpoint):
    async def scenario():
        host, port = broker_endpoint
        cloud = mqtt_runtime.CloudMqttClient(host, port, _client_id("cloud-roundtrip"))
        edge = mqtt_runtime.EdgeMqttClient(host, port, _client_id("edge-roundtrip"))
        handler = mqtt_runtime.CloudTaskHandler(
            cloud,
            FakeBehaviorEngine(),
            FakeReportGenerator(),
        )
        received = asyncio.Queue()

        async def on_cloud_result(topic, payload):
            await received.put((topic, payload))

        try:
            await _connect_client(cloud)
            await _connect_client(edge)
            await handler.start()
            await edge.subscribe("cloud/task/result/#", 1, on_cloud_result)
            await asyncio.sleep(0.2)

            await edge.publish(
                "cloud/task/request/classroom-301",
                json.dumps(_behavior_task_payload("edge-cloud-edge-1")),
                qos=1,
            )
            topic, payload = await asyncio.wait_for(received.get(), timeout=3)
        finally:
            await edge.disconnect()
            await cloud.disconnect()

        body = json.loads(payload)
        assert topic == "cloud/task/result/classroom-301"
        assert body["task_id"] == "edge-cloud-edge-1"
        assert body["status"] == "COMPLETED"
        assert body["result"]["talking"] == 1

    run(scenario())


def test_cloud_invalid_json_returns_failed_result(mqtt_runtime, broker_endpoint):
    async def scenario():
        host, port = broker_endpoint
        cloud = mqtt_runtime.CloudMqttClient(host, port, _client_id("cloud-invalid-json"))
        handler = mqtt_runtime.CloudTaskHandler(
            cloud,
            FakeBehaviorEngine(),
            FakeReportGenerator(),
        )
        result_probe = PahoProbe(host, port, _client_id("invalid-result-subscriber"))
        request_probe = PahoProbe(host, port, _client_id("invalid-request-publisher"))
        try:
            result_probe.connect()
            result_probe.subscribe("cloud/task/result/classroom-301", qos=1)
            await _connect_client(cloud)
            await handler.start()
            await asyncio.sleep(0.2)

            request_probe.connect()
            request_probe.publish(
                "cloud/task/request/classroom-301",
                '{"task_id": "invalid-json-1", "device_id": "classroom-301",',
                qos=1,
            )
            topic, payload, qos = await _next_probe_message(result_probe)
        finally:
            request_probe.close()
            result_probe.close()
            await cloud.disconnect()

        body = json.loads(payload)
        assert topic == "cloud/task/result/classroom-301"
        assert qos == 1
        assert body["task_id"] == "invalid-json-1"
        assert body["device_id"] == "classroom-301"
        assert body["status"] == "FAILED"
        assert "invalid json" in body["error"]

    run(scenario())
