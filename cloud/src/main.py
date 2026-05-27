#!/usr/bin/env python3
import asyncio
import logging
import os
import signal
from pathlib import Path

from app import CloudApp
from config import load_config


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    base_dir = Path(__file__).resolve().parents[1]
    config_path = Path(os.environ.get("CLOUD_CONFIG", base_dir / "config" / "cloud_config.yaml"))
    config = load_config(config_path)
    app = CloudApp(config)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await app.start()
    try:
        await stop_event.wait()
    finally:
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
