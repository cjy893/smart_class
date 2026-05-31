from pathlib import Path

from grpc_server import GrpcServer
from inference.behavior_engine import BehaviorEngine
from mqtt_client import MqttClient
from report.generator import ReportGenerator
from report.http_server import ReportHttpServer
from status_reporter import StatusReporter
from task_handler import CloudTaskHandler


class ModelLoader:
    def __init__(self, model_path: str):
        self.model_path = Path(model_path)

    def preload(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(f"model path does not exist: {self.model_path}")


class CloudApp:
    def __init__(
        self,
        config,
        mqtt=None,
        behavior_engine=None,
        report_generator=None,
        grpc_server=None,
        http_server=None,
        status_reporter=None,
        model_loader=None,
    ):
        self.config = config
        self.mqtt = mqtt or MqttClient(
            config.mqtt.broker_host,
            config.mqtt.broker_port,
            client_id=config.cloud_id,
        )
        self.model_loader = model_loader or ModelLoader(config.behavior.model_path)
        self.behavior_engine = behavior_engine
        self.report_generator = report_generator or ReportGenerator(config.paths.reports)
        self.grpc_server = grpc_server or GrpcServer(config.grpc.listen_address)
        self.http_server = http_server or ReportHttpServer(
            config.paths.reports,
            config.http.host,
            config.http.port,
        )
        self.status_reporter = status_reporter
        self.task_handler = None

    async def start(self) -> None:
        self.model_loader.preload()
        if self.behavior_engine is None:
            self.behavior_engine = BehaviorEngine.from_model_path(
                self.config.behavior.model_path,
                use_rule_engine=self.config.behavior.use_rule_engine,
            )
        self.task_handler = CloudTaskHandler(
            self.mqtt,
            self.behavior_engine,
            self.report_generator,
        )
        if self.status_reporter is None:
            self.status_reporter = StatusReporter(
                self.config.cloud_id,
                self.mqtt,
                interval_seconds=self.config.status_report.interval_seconds,
                task_queue=self.task_handler,
            )

        await self.mqtt.connect()
        await self.task_handler.start()
        await self.grpc_server.start()
        await self.http_server.start()
        await self.status_reporter.start()

    async def stop(self) -> None:
        if self.status_reporter:
            await self.status_reporter.stop()
        await self.http_server.stop()
        await self.mqtt.disconnect()
        await self.grpc_server.stop()
