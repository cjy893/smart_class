from pathlib import Path

import pytest

from config import ConfigError, load_config


def write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_cloud_config_with_required_sections(tmp_path):
    config_path = write_config(
        tmp_path / "cloud_config.yaml",
        """
cloud_id: cloud-main
mqtt:
  broker_host: 192.168.1.100
  broker_port: 1883
grpc:
  listen_address: 0.0.0.0:50051
paths:
  models: /data/models
  reports: /data/reports
behavior:
  model_path: /data/models/yolov5m.onnx
status_report:
  interval_seconds: 15
http:
  host: 127.0.0.1
  port: 8090
""",
    )

    config = load_config(config_path)

    assert config.cloud_id == "cloud-main"
    assert config.mqtt.broker_host == "192.168.1.100"
    assert config.mqtt.broker_port == 1883
    assert config.grpc.listen_address == "0.0.0.0:50051"
    assert config.paths.models == "/data/models"
    assert config.paths.reports == "/data/reports"
    assert config.behavior.model_path == "/data/models/yolov5m.onnx"
    assert config.status_report.interval_seconds == 15
    assert config.http.host == "127.0.0.1"
    assert config.http.port == 8090


def test_rejects_config_missing_required_mqtt_fields(tmp_path):
    config_path = write_config(
        tmp_path / "cloud_config.yaml",
        """
cloud_id: cloud-main
mqtt:
  broker_port: 1883
grpc:
  listen_address: 0.0.0.0:50051
paths:
  models: /data/models
  reports: /data/reports
behavior:
  model_path: /data/models/yolov5m.onnx
""",
    )

    with pytest.raises(ConfigError, match="mqtt.broker_host"):
        load_config(config_path)


def test_uses_documented_defaults_when_optional_fields_missing(tmp_path):
    config_path = write_config(
        tmp_path / "cloud_config.yaml",
        """
cloud_id: cloud-main
mqtt:
  broker_host: 192.168.1.100
  broker_port: 1883
grpc:
  listen_address: 0.0.0.0:50051
paths:
  models: /data/models
  reports: /data/reports
behavior:
  model_path: /data/models/yolov5m.onnx
""",
    )

    config = load_config(config_path)

    assert config.status_report.interval_seconds == 30
    assert config.behavior.use_rule_engine is True
    assert config.http.host == "0.0.0.0"
    assert config.http.port == 8081
