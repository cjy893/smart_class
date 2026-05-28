import asyncio

import pytest

from app import CloudApp
from config import CloudConfig, BehaviorConfig, GrpcConfig, MqttConfig, PathsConfig, StatusReportConfig
from fakes import FakeBehaviorEngine, FakeMetricsProvider, FakeMqttClient, FakeReportGenerator


class Recorder:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


class FakeGrpcServer:
    def __init__(self, recorder):
        self.recorder = recorder
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True
        self.recorder.record("grpc.start")

    async def stop(self):
        self.stopped = True
        self.recorder.record("grpc.stop")


class FakeStatusReporter:
    def __init__(self, recorder):
        self.recorder = recorder
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True
        self.recorder.record("status.start")

    async def stop(self):
        self.stopped = True
        self.recorder.record("status.stop")


class FakeHttpServer:
    def __init__(self, recorder):
        self.recorder = recorder

    async def start(self):
        self.recorder.record("http.start")

    async def stop(self):
        self.recorder.record("http.stop")


class FakeModelLoader:
    def __init__(self, recorder, should_fail=False):
        self.recorder = recorder
        self.should_fail = should_fail

    def preload(self):
        self.recorder.record("model.preload")
        if self.should_fail:
            raise FileNotFoundError("missing model")


class RecordingMqtt(FakeMqttClient):
    def __init__(self, recorder):
        super().__init__()
        self.recorder = recorder

    async def connect(self):
        await super().connect()
        self.recorder.record("mqtt.connect")

    async def subscribe(self, topic, qos, handler):
        await super().subscribe(topic, qos, handler)
        self.recorder.record("mqtt.subscribe")

    async def disconnect(self):
        await super().disconnect()
        self.recorder.record("mqtt.disconnect")


def run(coro):
    return asyncio.run(coro)


def config():
    return CloudConfig(
        cloud_id="cloud-main",
        mqtt=MqttConfig("127.0.0.1", 1883),
        grpc=GrpcConfig("0.0.0.0:50051"),
        paths=PathsConfig("/tmp/models", "/tmp/reports"),
        behavior=BehaviorConfig(True, "/tmp/models/yolov5m.onnx"),
        status_report=StatusReportConfig(30),
    )


def test_main_startup_order_loads_config_then_model_then_mqtt_then_grpc_then_status_reporter():
    recorder = Recorder()
    mqtt = RecordingMqtt(recorder)
    app = CloudApp(
        config(),
        mqtt=mqtt,
        behavior_engine=FakeBehaviorEngine(),
        report_generator=FakeReportGenerator(),
        grpc_server=FakeGrpcServer(recorder),
        http_server=FakeHttpServer(recorder),
        status_reporter=FakeStatusReporter(recorder),
        model_loader=FakeModelLoader(recorder),
    )

    run(app.start())

    assert recorder.events == [
        "model.preload",
        "mqtt.connect",
        "mqtt.subscribe",
        "grpc.start",
        "http.start",
        "status.start",
    ]


def test_startup_fails_fast_when_model_path_missing():
    recorder = Recorder()
    mqtt = RecordingMqtt(recorder)
    app = CloudApp(
        config(),
        mqtt=mqtt,
        behavior_engine=FakeBehaviorEngine(),
        report_generator=FakeReportGenerator(),
        grpc_server=FakeGrpcServer(recorder),
        http_server=FakeHttpServer(recorder),
        status_reporter=FakeStatusReporter(recorder),
        model_loader=FakeModelLoader(recorder, should_fail=True),
    )

    with pytest.raises(FileNotFoundError):
        run(app.start())

    assert recorder.events == ["model.preload"]
    assert mqtt.subscriptions == []


def test_shutdown_stops_status_reporter_mqtt_and_grpc():
    recorder = Recorder()
    mqtt = RecordingMqtt(recorder)
    grpc = FakeGrpcServer(recorder)
    status = FakeStatusReporter(recorder)
    app = CloudApp(
        config(),
        mqtt=mqtt,
        behavior_engine=FakeBehaviorEngine(),
        report_generator=FakeReportGenerator(),
        grpc_server=grpc,
        http_server=FakeHttpServer(recorder),
        status_reporter=status,
        model_loader=FakeModelLoader(recorder),
    )
    run(app.start())
    recorder.events.clear()

    run(app.stop())

    assert recorder.events == ["status.stop", "http.stop", "mqtt.disconnect", "grpc.stop"]


def test_app_starts_report_http_server_before_status_reporter():
    recorder = Recorder()
    app = CloudApp(
        config(),
        mqtt=RecordingMqtt(recorder),
        behavior_engine=FakeBehaviorEngine(),
        report_generator=FakeReportGenerator(),
        grpc_server=FakeGrpcServer(recorder),
        http_server=FakeHttpServer(recorder),
        status_reporter=FakeStatusReporter(recorder),
        model_loader=FakeModelLoader(recorder),
    )

    run(app.start())

    assert recorder.events == [
        "model.preload",
        "mqtt.connect",
        "mqtt.subscribe",
        "grpc.start",
        "http.start",
        "status.start",
    ]
