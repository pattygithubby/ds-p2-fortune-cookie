"""Entry point: `python -m fortune` runs one pod.

Planned start-up order:
    1. config = Config.from_env(os.environ)
    2. election = LeaderElection(); election.start()   # Bully node in a background thread
    3. app = create_app(FortuneSource(), election)
    4. aiohttp.web.run_app(app, port=config.web_port)   # election.stop() on shutdown
"""

import sys


def main() -> int:
    raise NotImplementedError("fortune is scaffolding only; see the module docstring")


if __name__ == "__main__":
    sys.exit(main())
