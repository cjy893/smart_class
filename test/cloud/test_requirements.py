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


def test_cloud_requirements_pins_board_compatible_protobuf_toolchain():
    requirements = Path("cloud/requirements.txt").read_text(encoding="utf-8")

    assert "protobuf==4.25.1" in requirements
    assert "grpcio-tools==1.60.0" in requirements
    assert "grpcio>=1.60" in requirements
