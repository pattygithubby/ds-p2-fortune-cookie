"""The analysis parts of the experiment scripts, on made-up data (no cluster needed)."""

import json

import pytest

import failover
import loadtest


def row(t, status, leader="", error=""):
    return {"t": t, "latency_ms": 2.0, "status": status, "error": error, "leader": leader,
            "pod": f"bully-{leader}" if leader else ""}


def test_summarize_percentiles_and_error_rate():
    rows = [{"start_s": i * 0.01, "latency_ms": float(i + 1), "status": 200, "pod": "bully-3"}
            for i in range(100)]
    rows.append({"start_s": 1.0, "latency_ms": 1000.0, "status": 0, "pod": ""})
    s = loadtest.summarize(rows, duration=2.0)
    assert s["requests"] == 101
    assert s["rps"] == pytest.approx(50.5)
    assert s["p50"] == pytest.approx(50.5)
    assert s["max"] == 100.0             # failed requests don't count towards latency
    assert s["error_rate"] == pytest.approx(1 / 101)
    assert s["pods"] == ["bully-3"]


def test_an_outage_runs_from_the_last_200_to_the_next():
    rows = [row(0.0, 200, "3"), row(1.0, 200, "3"), row(1.1, 0, error="timeout"),
            row(2.1, 0, error="ClientConnectorError"), row(2.2, 503, "2"), row(3.0, 200, "2")]
    (outage,) = failover.outages(rows, after=1.05)
    assert outage["gap"] == pytest.approx(2.0)
    assert (outage["failed"], outage["status_503"], outage["status_0"], outage["timeouts"]) == (3, 1, 2, 1)
    assert (outage["from"], outage["to"]) == ("3", "2")


def test_failures_before_the_action_are_ignored():
    rows = [row(0.0, 0), row(1.0, 200, "3"), row(2.0, 200, "3")]
    assert failover.outages(rows, after=0.5) == []


def test_leader_changes():
    rows = [row(0, 200, "3"), row(1, 0), row(2, 200, "2"), row(3, 200, "2"), row(4, 200, "3")]
    assert failover.leader_changes(rows) == [(2.0, "3", "2"), (4.0, "2", "3")]


def test_parse_kubectl_timestamp():
    assert failover.parse_log_line("not a log line") is None
    assert failover.parse_timestamp("1970-01-01T00:00:01.123456789Z") == pytest.approx(1.123456)


def test_analyze_a_run():
    t = 1_000_000.0
    meta = {"run": 1, "mode": "delete", "victim": "bully-3", "t_action_start": t - 0.1,
            "t_action": t, "interval": 0.1}
    rows = [row(t - 0.5, 200, "3"), row(t + 0.5, 0), row(t + 2.0, 200, "2")]

    def entry(offset, logger, message):
        return (t + offset, logger, message)

    logs = {
        "bully-2": [entry(-5, "bully", "NORMAL: node 3 is coordinator"),
                    entry(1.0, "bully.transport_udp", "-> AreYouThere to node 3: no answer"),
                    entry(1.2, "bully", "NORMAL: coordinator of nodes [1, 2]")],
        "bully-3": [entry(2.5, "fortune.election", "improved Bully, node 3 of 3, T = 1.0 s")],
    }
    r = failover.analyze(meta, rows, logs)
    assert r["detection"] == pytest.approx(1.0, abs=1e-3)
    assert r["election"] == pytest.approx(0.2, abs=1e-3)
    assert r["routing"] == pytest.approx(0.8, abs=1e-3)
    assert r["gap"] == pytest.approx(2.5)
    assert r["back"] == pytest.approx(2.5, abs=1e-3)
    assert (r["failed"], r["new_leader"]) == (1, "2")


def test_save_and_load_round_trip(tmp_path):
    meta = {"run": 1, "mode": "delete", "victim": "bully-3", "t_action_start": 0, "t_action": 0}
    rows = [{"t": "1.5", "latency_ms": "2.0", "status": "200", "error": "", "leader": "3",
             "pod": "bully-3"}]
    logs = {"bully-2": "1970-01-01T00:00:01.000000000Z 00:00:01.000 bully: DOWN: starting\n"}
    failover.save(tmp_path / "f", [(meta, rows, logs)])
    ((meta2, rows2, logs2),) = failover.load(tmp_path / "f.json")
    assert meta2 == meta
    assert rows2 == [{"run": "1", **rows[0]}]
    assert logs2 == {"bully-2": [(1.0, "bully", "DOWN: starting")]}
