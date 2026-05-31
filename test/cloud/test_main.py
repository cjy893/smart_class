import asyncio
import builtins
import importlib.util
import signal
import sys
from pathlib import Path

import pytest

import main


class NoSignalLoop:
    def __init__(self):
        self.handlers = []

    def add_signal_handler(self, sig, callback):
        self.handlers.append((sig, callback))
        raise NotImplementedError("not supported on Windows")


class SignalLoop:
    def __init__(self):
        self.handlers = []

    def add_signal_handler(self, sig, callback):
        self.handlers.append((sig, callback))


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_register_stop_signal_ignores_windows_unsupported_signal_handlers(sig):
    stop_event = asyncio.Event()
    loop = NoSignalLoop()

    main.register_stop_signal(loop, sig, stop_event)

    assert not stop_event.is_set()


def test_register_stop_signal_sets_event_on_posix_signal_handler():
    stop_event = asyncio.Event()
    loop = SignalLoop()

    main.register_stop_signal(loop, signal.SIGINT, stop_event)
    _, callback = loop.handlers[0]
    callback()

    assert stop_event.is_set()


def test_parse_args_supports_check_mode():
    args = main.parse_args(["--check", "--config", "cloud/config/cloud_config.yaml"])

    assert args.check is True
    assert args.config == "cloud/config/cloud_config.yaml"


def test_run_check_returns_zero_when_doctor_passes(tmp_path, capsys):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    model_path = model_dir / "yolov5m.onnx"
    model_path.write_bytes(b"model")
    config_path = tmp_path / "cloud_config.yaml"
    config_path.write_text(
        f"""
cloud_id: cloud-main
mqtt:
  broker_host: 192.168.137.2
  broker_port: 1883
grpc:
  listen_address: 0.0.0.0:50051
paths:
  models: {model_dir}
  reports: {tmp_path / "reports"}
behavior:
  model_path: {model_path}
""",
        encoding="utf-8",
    )

    exit_code = main.run_check(config_path, dependency_names=("yaml",))

    assert exit_code == 0
    assert "cloud check passed" in capsys.readouterr().out


def test_run_check_returns_nonzero_when_doctor_fails(tmp_path, capsys):
    config_path = tmp_path / "cloud_config.yaml"
    config_path.write_text(
        f"""
cloud_id: cloud-main
mqtt:
  broker_host: 192.168.137.2
  broker_port: 1883
grpc:
  listen_address: 0.0.0.0:50051
paths:
  models: {tmp_path / "models"}
  reports: {tmp_path / "reports"}
behavior:
  model_path: {tmp_path / "models" / "yolov5m.onnx"}
""",
        encoding="utf-8",
    )

    exit_code = main.run_check(config_path, dependency_names=("yaml",))

    assert exit_code == 1
    assert "cloud check failed" in capsys.readouterr().out


def test_importing_main_for_check_mode_does_not_import_cloud_app(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "app":
            raise AssertionError("main.py should import CloudApp only when starting the service")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    module_name = "cloud_main_check_import_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, Path("cloud/src/main.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    spec.loader.exec_module(module)

    assert hasattr(module, "run_check")


def test_importing_main_for_help_mode_does_not_import_config(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "config":
            raise AssertionError("main.py should import config only when checking or starting")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    module_name = "cloud_main_help_import_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, Path("cloud/src/main.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    spec.loader.exec_module(module)

    with pytest.raises(SystemExit) as exc:
        module.parse_args(["--help"])
    assert exc.value.code == 0
