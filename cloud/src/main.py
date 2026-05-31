#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from doctor import DEFAULT_DEPENDENCIES, CloudDoctor


def register_stop_signal(loop, sig: signal.Signals, stop_event: asyncio.Event) -> None:
    try:
        loop.add_signal_handler(sig, stop_event.set)
    except (AttributeError, NotImplementedError, RuntimeError):
        return


def default_config_path() -> Path:
    base_dir = Path(__file__).resolve().parents[1]
    return Path(os.environ.get("CLOUD_CONFIG", base_dir / "config" / "cloud_config.yaml"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the smart_class cloud service.")
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="Path to cloud_config.yaml. Defaults to CLOUD_CONFIG or cloud/config/cloud_config.yaml.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate cloud configuration, Python dependencies, model path, and report directory.",
    )
    return parser.parse_args(argv)


def run_check(config_path: str | Path, dependency_names: tuple[str, ...] = DEFAULT_DEPENDENCIES) -> int:
    from config import load_config

    config = load_config(config_path)
    result = CloudDoctor(config, dependency_names=dependency_names).run()
    for message in result.messages:
        print(f"[OK] {message}")
    for error in result.errors:
        print(f"[ERROR] {error}")
    if result.ok:
        print("cloud check passed")
        return 0
    print("cloud check failed")
    return 1


async def main(config_path: str | Path | None = None) -> None:
    from app import CloudApp
    from config import load_config

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config = load_config(config_path or default_config_path())
    app = CloudApp(config)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        register_stop_signal(loop, sig, stop_event)

    await app.start()
    try:
        await stop_event.wait()
    finally:
        await app.stop()


if __name__ == "__main__":
    args = parse_args()
    if args.check:
        raise SystemExit(run_check(args.config))
    try:
        asyncio.run(main(args.config))
    except KeyboardInterrupt:
        sys.exit(0)
