"""LeaderElection with real Bully nodes over UDP on localhost, as in a pod but much faster."""

import socket
import time

import pytest

from fortune.election import LeaderElection

FAST = 0.05   # seconds between check() and timeout() rounds; the pods use 2 s


def wait_until(condition, seconds=10.0):
    """Poll until condition() is true. Returns False if it never became true."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def free_port_prefix(n):
    """A prefix P such that UDP ports P1 .. Pn are free, for the template "127.0.0.1:P{id}"."""
    for prefix in range(4731, 6500, 7):
        sockets = []
        try:
            for node_id in range(1, n + 1):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sockets.append(sock)
                sock.bind(("0.0.0.0", int(f"{prefix}{node_id}")))
            return prefix
        except OSError:
            continue
        finally:
            for sock in sockets:
                sock.close()
    pytest.skip("no free UDP ports found")


def election(tmp_path, node_id, n, prefix=None):
    env = {
        "BULLY_ID": str(node_id),
        "BULLY_N": str(n),
        "BULLY_PEERS": f"127.0.0.1:{prefix}{{id}}" if prefix else "127.0.0.1:9000",
        "BULLY_PORT": f"{prefix}{node_id}" if prefix else "0",
        "BULLY_STATE_DIR": str(tmp_path / f"node{node_id}"),
        "BULLY_TIMEOUT": "0.2",
    }
    return LeaderElection(env, interval=FAST)


def test_nobody_leads_before_start(tmp_path):
    e = election(tmp_path, 1, 1)
    assert e.is_leader() is False
    assert e.leader_id() is None


def test_bad_configuration_is_reported_on_start():
    with pytest.raises(ValueError, match="BULLY_N"):
        LeaderElection({}).start()


def test_single_node_becomes_leader_and_stops(tmp_path):
    e = election(tmp_path, 1, 1)
    e.start()
    try:
        assert wait_until(e.is_leader)
        assert e.leader_id() == 1
        assert e.node_id == 1
    finally:
        e.stop()
    assert not e._thread.is_alive()


def test_follower_takes_over_when_the_leader_stops(tmp_path):
    prefix = free_port_prefix(2)
    low, high = election(tmp_path, 1, 2, prefix), election(tmp_path, 2, 2, prefix)
    low.start()
    high.start()
    try:
        assert wait_until(lambda: high.is_leader() and low.leader_id() == 2)
        assert not low.is_leader()

        high.stop()   # what `kubectl delete pod` does to the leader
        assert wait_until(low.is_leader)
        assert low.leader_id() == 1
    finally:
        low.stop()
        high.stop()
