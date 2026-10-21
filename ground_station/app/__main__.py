"""Entry point: python -m ground_station.app --link <url>."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import uvicorn

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ground_station.app.main import CONFIG_PATH, create_app
from ground_station.app.state import load_config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    config = load_config(CONFIG_PATH)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--link", default=config["link"]["default_port"],
                         help='"COM5", "/dev/ttyUSB0", "socket://127.0.0.1:8765", or "auto"')
    parser.add_argument("--any-port", action="store_true",
                         help="when --link auto, probe every serial port, not just known ESP32 chips")
    parser.add_argument("--replay", default=None, help="not yet implemented (Phase 7)")
    return parser.parse_args(argv)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    if args.replay is not None:
        raise NotImplementedError("--replay is implemented in Phase 7 (docs/06)")
    app = create_app(args)
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    try:
        asyncio.run(server.serve())
    except SystemExit:
        # F19: uvicorn.Server.startup() catches a bind OSError itself
        # (e.g. a second ground station on the same port), logs it via its
        # own logger (the "ERROR: [Errno ...]" line above this), and calls
        # sys.exit() directly -- it never reaches an `except OSError` in
        # calling code. Add one clear, actionable line on top of uvicorn's
        # own (which stays, since it has the real OS error text);
        # server.started distinguishes this from a normal shutdown exit.
        if not server.started:
            print(
                "Could not start the ground station -- is another instance "
                "already running? Stop it first, or use a different port.",
                file=sys.stderr,
            )
        raise


if __name__ == "__main__":
    main()
