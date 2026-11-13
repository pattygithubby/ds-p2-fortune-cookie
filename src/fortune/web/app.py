"""The aiohttp application factory.

Planned routes:
    GET /              static/index.html
    GET /static/...    style.css, app.js
    GET /api/fortune   {"fortune": "...", "leader": <id>}
    GET /healthz       200 while the process is alive (liveness probe)
    GET /leader        200 only on the leader, 503 otherwise (readiness probe, so the
                       web Service routes traffic to the leader pod alone)
"""

from importlib.resources import files

from aiohttp import web

from ..election import LeaderElection
from ..fortunes import FortuneSource

STATIC_DIR = files("fortune") / "web" / "static"


def create_app(fortunes: FortuneSource, election: LeaderElection) -> web.Application:
    """Build the web application. Dependencies are passed in so tests can use fakes."""
    raise NotImplementedError
