from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class MqttConfig:
    broker_host: str
    broker_port: int


@dataclass(frozen=True)
class GrpcConfig:
    listen_address: str


@dataclass(frozen=True)
class PathsConfig:
    models: str
    reports: str


@dataclass(frozen=True)
class BehaviorConfig:
    use_rule_engine: bool
    model_path: str


@dataclass(frozen=True)
class StatusReportConfig:
    interval_seconds: int = 30


@dataclass(frozen=True)
class HttpConfig:
    host: str = "0.0.0.0"
    port: int = 8081


@dataclass(frozen=True)
class CloudConfig:
    cloud_id: str
    mqtt: MqttConfig
    grpc: GrpcConfig
    paths: PathsConfig
    behavior: BehaviorConfig
    status_report: StatusReportConfig
    http: HttpConfig = HttpConfig()


def load_config(path: str | Path) -> CloudConfig:
    config_path = Path(path).resolve()
    config_dir = config_path.parent
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return CloudConfig(
        cloud_id=_required(raw, "cloud_id"),
        mqtt=MqttConfig(
            broker_host=_required(raw, "mqtt.broker_host"),
            broker_port=int(_required(raw, "mqtt.broker_port")),
        ),
        grpc=GrpcConfig(
            listen_address=_required(raw, "grpc.listen_address"),
        ),
        paths=PathsConfig(
            models=_resolve_config_path(config_dir, _required(raw, "paths.models")),
            reports=_resolve_config_path(config_dir, _required(raw, "paths.reports")),
        ),
        behavior=BehaviorConfig(
            use_rule_engine=bool(_get(raw, "behavior.use_rule_engine", True)),
            model_path=_resolve_config_path(config_dir, _required(raw, "behavior.model_path")),
        ),
        status_report=StatusReportConfig(
            interval_seconds=int(_get(raw, "status_report.interval_seconds", 30)),
        ),
        http=HttpConfig(
            host=str(_get(raw, "http.host", "0.0.0.0")),
            port=int(_get(raw, "http.port", 8081)),
        ),
    )


def _required(raw: dict[str, Any], dotted_key: str) -> Any:
    value = _get(raw, dotted_key, None)
    if value in (None, ""):
        raise ConfigError(f"missing required config field: {dotted_key}")
    return value


def _get(raw: dict[str, Any], dotted_key: str, default: Any) -> Any:
    current: Any = raw
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _resolve_config_path(config_dir: Path, value: Any) -> str:
    path = Path(str(value))
    if path.is_absolute():
        return str(path)
    return str((config_dir / path).resolve())
