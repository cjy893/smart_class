from pathlib import Path

from config import BehaviorConfig, CloudConfig, GrpcConfig, HttpConfig, MqttConfig, PathsConfig, StatusReportConfig
from doctor import CloudDoctor


def config(tmp_path: Path) -> CloudConfig:
    model_dir = tmp_path / "models"
    reports_dir = tmp_path / "reports"
    return CloudConfig(
        cloud_id="cloud-main",
        mqtt=MqttConfig("192.168.137.2", 1883),
        grpc=GrpcConfig("0.0.0.0:50051"),
        paths=PathsConfig(str(model_dir), str(reports_dir)),
        behavior=BehaviorConfig(True, str(model_dir / "yolov5m.onnx")),
        status_report=StatusReportConfig(30),
        http=HttpConfig("127.0.0.1", 8081),
    )


def test_cloud_doctor_passes_when_required_paths_and_dependencies_are_available(tmp_path):
    cfg = config(tmp_path)
    Path(cfg.paths.models).mkdir(parents=True)
    Path(cfg.behavior.model_path).write_bytes(b"model")

    result = CloudDoctor(cfg, dependency_names=("yaml",)).run()

    assert result.ok is True
    assert result.errors == []
    assert Path(cfg.paths.reports).is_dir()
    assert "model file exists" in result.messages


def test_cloud_doctor_reports_missing_model_file(tmp_path):
    cfg = config(tmp_path)
    Path(cfg.paths.models).mkdir(parents=True)

    result = CloudDoctor(cfg, dependency_names=("yaml",)).run()

    assert result.ok is False
    assert any("model file is missing" in error for error in result.errors)


def test_cloud_doctor_reports_missing_python_dependency(tmp_path):
    cfg = config(tmp_path)
    Path(cfg.paths.models).mkdir(parents=True)
    Path(cfg.behavior.model_path).write_bytes(b"model")

    result = CloudDoctor(cfg, dependency_names=("definitely_missing_cloud_dependency",)).run()

    assert result.ok is False
    assert result.errors == ["missing Python package: definitely_missing_cloud_dependency"]
