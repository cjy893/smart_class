from pathlib import Path


def test_windows_cloud_runner_script_exposes_check_and_run_modes():
    script = Path("cloud/run_cloud_windows.ps1").read_text(encoding="utf-8")

    for expected in [
        "param(",
        "[switch]$Check",
        "$env:CLOUD_CONFIG",
        "cloud/src/main.py",
        "--check",
        "--config",
    ]:
        assert expected in script
