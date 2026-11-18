"""The aiohttp application factory.

Routes:
    GET /              static/index.html                      (leader only)
    GET /static/...    style.css, app.js
    GET /api/fortune   {"fortune": "...", "leader": <id>, "pod": "<host name>"}   (leader only)
    GET /healthz       200 while the process is alive (liveness probe)
    GET /leader        200 only on the leader, 503 otherwise (readiness probe, so the
                       web Service routes traffic to the leader pod alone)

Only the leader hosts the website. A follower answers the leader-only routes with 503 and
the current leader's id. Normally no traffic reaches a follower, because it never passes the
readiness probe. It can for a moment after a takeover, while the old leader is still listed
in the Service, and the page then simply retries.
"""

import socket
from importlib.resources import files
from pathlib import Path

from aiohttp import web

from ..election import LeaderElection
from ..fortunes import FortuneSource

STATIC_DIR = files("fortune") / "web" / "static"
NO_STORE = {"Cache-Control": "no-store"}   # every answer must come from the current leader


def create_app(fortunes: FortuneSource, election: LeaderElection) -> web.Application:
    """Build the web application. Dependencies are passed in so tests can use fakes."""
    pod = socket.gethostname()   # the pod name on Kubernetes, e.g. bully-2
    static_dir = Path(str(STATIC_DIR))

    def not_leader() -> web.Response:
        body = {"error": "not the leader", "leader": election.leader_id(), "pod": pod}
        return web.json_response(body, status=503, headers=NO_STORE)

    async def index(request: web.Request) -> web.StreamResponse:
        if not election.is_leader():
            return not_leader()
        return web.FileResponse(static_dir / "index.html", headers=NO_STORE)

    async def fortune(request: web.Request) -> web.Response:
        if not election.is_leader():
            return not_leader()
        body = {"fortune": fortunes.random(), "leader": election.leader_id(), "pod": pod}
        return web.json_response(body, headers=NO_STORE)

    async def healthz(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def leader(request: web.Request) -> web.Response:
        status = 200 if election.is_leader() else 503
        body = {"leader": election.leader_id(), "pod": pod}
        return web.json_response(body, status=status, headers=NO_STORE)

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/fortune", fortune)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/leader", leader)
    app.router.add_static("/static", static_dir)
    return app
