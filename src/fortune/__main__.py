"""Entry point: `python -m fortune` runs one pod.

Start-up order:
    1. config = Config.from_env(os.environ)
    2. election = LeaderElection(); election.start()   # Bully node in a background thread
    3. app = create_app(FortuneSource(), election)
    4. aiohttp.web.run_app(app, port=config.web_port)   # election.stop() on shutdown

The election is configured by the BULLY_* variables (see src/bully/__main__.py). To run
one pod on your own machine:
    BULLY_N=1 BULLY_ID=1 BULLY_PEERS=127.0.0.1:9000 BULLY_STATE_DIR=.state python -m fortune
"""

import asyncio
import logging
import os
import sys

from aiohttp import web

from .config import Config
from .election import LeaderElection
from .fortunes import FortuneSource
from .web.app import create_app

# Millisecond timestamps: experiment 2 measures election times from these log lines
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(name)s: %(message)s"


def main() -> int:
    try:
        config = Config.from_env(os.environ)
    except ValueError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2
    logging.basicConfig(level=config.log_level, format=LOG_FORMAT, datefmt="%H:%M:%S",
                        stream=sys.stdout)

    election = LeaderElection()
    try:
        election.start()
    except ValueError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2

    app = create_app(FortuneSource(), election)

    async def stop_election(app: web.Application) -> None:
        # stop() waits for the node's thread, which can take a few T; keep the loop free
        await asyncio.to_thread(election.stop)

    app.on_cleanup.append(stop_election)
    logging.getLogger("fortune").info("website on port %d", config.web_port)
    # run_app stops on SIGTERM (`kubectl delete pod`) and Ctrl+C, then runs on_cleanup.
    # No access log: the load test would bury the election's log lines.
    web.run_app(app, port=config.web_port, access_log=None, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
