from dataclasses import dataclass
from importlib import import_module
from pathlib import Path


DEFAULT_DEPENDENCIES = (
    "yaml",
    "paho.mqtt.client",
    "grpc",
    "cv2",
    "numpy",
    "psutil",
)


@dataclass(frozen=True)
class DoctorResult:
    ok: bool
    messages: list[str]
    errors: list[str]


class CloudDoctor:
    def __init__(self, config, dependency_names: tuple[str, ...] = DEFAULT_DEPENDENCIES):
        self.config = config
        self.dependency_names = dependency_names

    def run(self) -> DoctorResult:
        messages: list[str] = []
        errors: list[str] = []

        for dependency in self.dependency_names:
            try:
                import_module(dependency)
                messages.append(f"Python package available: {dependency}")
            except ImportError:
                errors.append(f"missing Python package: {dependency}")

        model_dir = Path(self.config.paths.models)
        if model_dir.is_dir():
            messages.append(f"models directory exists: {model_dir}")
        else:
            errors.append(f"models directory is missing: {model_dir}")

        model_path = Path(self.config.behavior.model_path)
        if model_path.is_file():
            messages.append("model file exists")
        else:
            errors.append(f"model file is missing: {model_path}")

        reports_dir = Path(self.config.paths.reports)
        try:
            reports_dir.mkdir(parents=True, exist_ok=True)
            messages.append(f"reports directory is writable: {reports_dir}")
        except OSError as exc:
            errors.append(f"reports directory is not writable: {reports_dir} ({exc})")

        return DoctorResult(ok=not errors, messages=messages, errors=errors)
