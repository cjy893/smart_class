from pathlib import Path


def test_windows_cloud_guide_documents_setup_test_and_run_flow():
    guide = Path("docs/CLOUD_WINDOWS_GUIDE.md").read_text(encoding="utf-8")

    for expected in [
        "python -m venv .venv",
        "pip install -r cloud/requirements.txt",
        "pip install pytest",
        "pytest test/cloud -q",
        "python cloud/src/main.py --check",
        ".\\cloud\\run_cloud_windows.ps1 -Check",
        "python cloud/src/main.py",
        ".\\cloud\\run_cloud_windows.ps1",
        "CLOUD_CONFIG",
        "cloud/config/cloud_config.yaml",
        "cloud/data/models/yolov5m.onnx",
        "cloud/data/reports",
        "Mosquitto",
    ]:
        assert expected in guide


def test_requirements_cloud_config_example_matches_runtime_fields():
    requirements = Path("docs/REQUIREMENTS.md").read_text(encoding="utf-8")

    assert "cloud_id:" in requirements
    assert "listen_address:" in requirements
    assert "edge_address:" not in requirements
    assert 'model_path: "../data/models/yolov5m.onnx"' in requirements
