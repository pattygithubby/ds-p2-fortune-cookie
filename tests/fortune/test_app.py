"""The web routes, with a fake election so no Bully node or cluster is needed."""

import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from fortune.fortunes import FortuneSource
from fortune.web.app import create_app


class FakeElection:
    def __init__(self, leader: bool, leader_id: int | None):
        self.leader = leader
        self.current_leader = leader_id

    def is_leader(self) -> bool:
        return self.leader

    def leader_id(self) -> int | None:
        return self.current_leader


LEADER = FakeElection(leader=True, leader_id=3)
FOLLOWER = FakeElection(leader=False, leader_id=3)
ELECTING = FakeElection(leader=False, leader_id=None)


@pytest.fixture
def fortunes(tmp_path):
    path = tmp_path / "fortunes.txt"
    path.write_text("one\ntwo\n", encoding="utf-8")
    return FortuneSource(path)


def get(app, path):
    """GET path from app; returns (status, headers, body), with JSON bodies decoded."""
    async def run():
        async with TestClient(TestServer(app)) as client:
            response = await client.get(path)
            if response.content_type == "application/json":
                body = await response.json()
            else:
                body = await response.text()
            return response.status, response.headers, body
    return asyncio.run(run())


def test_leader_serves_the_page(fortunes):
    status, _, body = get(create_app(fortunes, LEADER), "/")
    assert status == 200
    assert "Get another cookie" in body


@pytest.mark.parametrize("path", ["/static/app.js", "/static/style.css"])
def test_static_files_are_served(fortunes, path):
    status, _, _ = get(create_app(fortunes, LEADER), path)
    assert status == 200


def test_leader_serves_a_fortune(fortunes):
    status, headers, body = get(create_app(fortunes, LEADER), "/api/fortune")
    assert status == 200
    assert body["fortune"] in ("one", "two")
    assert body["leader"] == 3
    assert body["pod"]
    assert headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("path", ["/", "/api/fortune"])
@pytest.mark.parametrize("election, leader_id", [(FOLLOWER, 3), (ELECTING, None)])
def test_only_the_leader_hosts_the_website(fortunes, path, election, leader_id):
    status, _, body = get(create_app(fortunes, election), path)
    assert status == 503
    assert body["error"] == "not the leader"
    assert body["leader"] == leader_id


@pytest.mark.parametrize("election", [LEADER, FOLLOWER, ELECTING])
def test_healthz_is_always_ok(fortunes, election):
    status, _, body = get(create_app(fortunes, election), "/healthz")
    assert (status, body) == (200, "ok")


@pytest.mark.parametrize("election, expected", [(LEADER, 200), (FOLLOWER, 503), (ELECTING, 503)])
def test_leader_endpoint_is_the_readiness_probe(fortunes, election, expected):
    status, _, body = get(create_app(fortunes, election), "/leader")
    assert status == expected
    assert body["leader"] == election.leader_id()
