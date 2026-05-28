from pathlib import Path


def test_cloud_requirements_declares_runtime_dependencies():
    requirements = Path("cloud/requirements.txt").read_text(encoding="utf-8")

    for dependency in [
        "paho-mqtt",
        "grpcio",
        "grpcio-tools",
        "protobuf",
        "opencv-python",
        "numpy",
        "PyYAML",
        "psutil",
        "jinja2",
    ]:
        assert dependency in requirements
