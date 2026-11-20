"""Experiment 2: leader failure.

    python experiments/failover.py run --mode delete --runs 5 --out experiments/results/failover-delete
    python experiments/failover.py report experiments/results/failover-delete.json --plot ...

`run` polls GET /api/fortune like a user would (one keep-alive connection, a request every
--interval s, --timeout s per request) and, after --before s, takes the leader out:

    delete   kubectl delete pod <leader>           (SIGTERM; the StatefulSet recreates it)
    force    kubectl delete pod <leader> --grace-period=0 --force
    scale    kubectl scale statefulset bully --replicas=2   (it stays down; scaled back to 3
             after --restore-after s, so the return of node 3 is recorded too)

It keeps polling for --after s, and repeats this --runs times. All runs go into three files
(rewritten after every run, so an interrupted series keeps the finished runs):
    <out>.csv       one row per request: run, t (Unix time), latency_ms, status (0 = no HTTP
                    answer), error (for status 0: "timeout" or the aiohttp exception), leader, pod
    <out>.json      {"runs": [...]}: each run's settings and the times of the action
    <out>-pods.log  `kubectl logs --timestamps` of every pod, each line prefixed with
                    "run<K> <pod>". The old leader's log is followed from before the action
                    (pod "<name>-before"), so its last lines survive the pod being deleted.

Before each run it waits until all pods are up and node 3 has served for a few seconds.

`report` computes, per run, the times below and their mean/min/max over the runs:
    detection   action -> first "-> ... to node <old>: no answer" in a survivor's log
    election    detection -> first "NORMAL: coordinator of nodes" in a survivor's log
    routing     election -> first 200 from the new leader (readiness probe + endpoint update)
    gap         last 200 before the action -> first 200 after it (what users notice)
    failed      requests in the gap that did not get a 200
    back        action (scale: scaling back to 3) -> the old leader's pod has started again
and the later outages (node 3 taking over again after its restart).
"""

import argparse
import asyncio
import csv
import json
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

FIELDS = ["t", "latency_ms", "status", "error", "leader", "pod"]
PODS = ["bully-1", "bully-2", "bully-3"]


# ---------------------------------------------------------------- client side

async def fetch(session: aiohttp.ClientSession, url: str) -> dict:
    start = time.time()
    status, error, leader, pod = 0, "", "", ""
    try:
        async with session.get(url) as response:
            status = response.status
            try:
                body = await response.json(content_type=None)
                leader, pod = str(body.get("leader") or ""), str(body.get("pod") or "")
            except ValueError:
                pass
    except asyncio.TimeoutError:
        error = "timeout"
    except aiohttp.ClientError as e:
        error = type(e).__name__   # e.g. ClientConnectorError, ServerDisconnectedError
    return {"t": round(start, 6), "latency_ms": round((time.time() - start) * 1000, 3),
            "status": status, "error": error, "leader": leader, "pod": pod}


def kubectl(*args: str, check: bool = True) -> str:
    result = subprocess.run(["kubectl", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def running_pods() -> list[str]:
    out = kubectl("get", "pods", "-l", "app=fortune-cookie", "-o",
                  "jsonpath={range .items[?(@.status.phase=='Running')]}{.metadata.name} {end}")
    return sorted(out.split())


async def wait_stable(url: str, settle: float, limit: float = 120) -> None:
    """Wait until all three pods run and node 3 has answered 200 for `settle` seconds."""
    deadline = time.time() + limit
    since = None
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1)) as session:
        while time.time() < deadline:
            row = await fetch(session, url)
            ok = row["status"] == 200 and row["leader"] == "3" and running_pods() == PODS
            since = (since or time.time()) if ok else None
            if since and time.time() - since >= settle:
                return
            await asyncio.sleep(0.5)
    raise RuntimeError("cluster did not settle with node 3 as leader")


async def one_run(args, number: int, tmp: Path) -> tuple[dict, list[dict], dict[str, str]]:
    """One failure; returns (meta, rows, {pod: log text})."""
    await wait_stable(args.url, args.settle)
    rows, meta = [], {"run": number, "mode": args.mode, "url": args.url,
                      "interval": args.interval, "timeout": args.timeout,
                      "context": kubectl("config", "current-context").strip()}
    meta["t_start"] = t_start = time.time()
    follow = follow_file = None
    acted = restored = False

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=args.timeout)) as session:
        next_poll = t_start
        while time.time() < t_start + args.before + args.after:
            row = await fetch(session, args.url)
            rows.append(row)

            if not acted and time.time() >= t_start + args.before:
                victim = next(r["pod"] for r in reversed(rows) if r["status"] == 200)
                meta["victim"] = victim
                follow_file = tmp / f"{victim}-before.log"
                follow = subprocess.Popen(
                    ["kubectl", "logs", "-f", "--timestamps", victim],
                    stdout=follow_file.open("w"), stderr=subprocess.DEVNULL)
                await asyncio.sleep(0.3)   # let `logs -f` attach before the pod goes away
                if args.mode == "scale":
                    command = ["scale", "statefulset", "bully", "--replicas=2"]
                elif args.mode == "force":
                    command = ["delete", "pod", victim, "--grace-period=0", "--force", "--wait=false"]
                else:
                    command = ["delete", "pod", victim, "--wait=false"]
                meta["t_action_start"] = time.time()
                await asyncio.to_thread(kubectl, *command)
                meta["t_action"] = time.time()   # the API server has accepted the action
                acted = True

            if (args.mode == "scale" and acted and not restored
                    and time.time() >= meta["t_action"] + args.restore_after):
                meta["t_restore"] = time.time()
                await asyncio.to_thread(kubectl, "scale", "statefulset", "bully", "--replicas=3")
                restored = True

            # after a slow request, skip the missed ticks instead of sending them in a burst
            next_poll = max(next_poll + args.interval, time.time())
            await asyncio.sleep(max(0.0, next_poll - time.time()))

    logs = {}
    if follow:
        follow.terminate()
        follow.wait()
        logs[follow_file.stem] = follow_file.read_text()
    since = datetime.fromtimestamp(t_start, timezone.utc).isoformat(timespec="seconds")
    for pod in running_pods():
        logs[pod] = kubectl("logs", "--timestamps", f"--since-time={since}", pod, check=False)
    return meta, rows, logs


def save(out: Path, runs: list[tuple[dict, list[dict], dict[str, str]]]) -> None:
    """Write all runs to <out>.csv, <out>.json and <out>-pods.log."""
    with out.with_name(out.name + ".csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["run", *FIELDS])
        writer.writeheader()
        for meta, rows, _ in runs:
            writer.writerows({"run": meta["run"], **row} for row in rows)
    out.with_name(out.name + ".json").write_text(
        json.dumps({"runs": [meta for meta, _, _ in runs]}, indent=2) + "\n")
    with out.with_name(out.name + "-pods.log").open("w") as f:
        for meta, _, logs in runs:
            for pod, text in sorted(logs.items()):
                for line in text.splitlines():
                    f.write(f"run{meta['run']} {pod} {line}\n")


def load(json_path: Path) -> list[tuple[dict, list[dict], dict[str, list]]]:
    """The runs saved by `save`: [(meta, rows, {pod: [(time, logger, message)]})]."""
    base = json_path.with_suffix("")
    metas = json.loads(json_path.read_text())["runs"]
    rows, logs = {}, {}
    with base.with_name(base.name + ".csv").open(newline="") as f:
        for row in csv.DictReader(f):
            rows.setdefault(int(row["run"]), []).append(row)
    log_path = base.with_name(base.name + "-pods.log")
    for line in log_path.read_text().splitlines():
        run, pod, rest = line.split(" ", 2)
        entry = parse_log_line(rest)
        if entry:
            logs.setdefault(int(run.removeprefix("run")), {}).setdefault(pod, []).append(entry)
    return [(m, rows.get(m["run"], []), logs.get(m["run"], {})) for m in metas]


def cmd_run(args) -> None:
    import tempfile

    args.out.parent.mkdir(parents=True, exist_ok=True)
    runs = []
    with tempfile.TemporaryDirectory() as tmp:
        for k in range(1, args.runs + 1):
            print(f"run {k}/{args.runs} ({args.mode})")
            meta, rows, logs = asyncio.run(one_run(args, k, Path(tmp)))
            runs.append((meta, rows, logs))
            save(args.out, runs)
            parsed = {pod: [e for e in map(parse_log_line, text.splitlines()) if e]
                      for pod, text in logs.items()}
            print(summary_line(analyze(meta, rows, parsed)))
    if args.mode == "scale":
        kubectl("scale", "statefulset", "bully", "--replicas=3")
    print(f"wrote {args.out}.csv, {args.out}.json, {args.out}-pods.log")


# ---------------------------------------------------------------- analysis

LOG_LINE = re.compile(r"^(\S+) \S+ (\S+): (.*)$")


def parse_timestamp(text: str) -> float:
    """RFC 3339 with nanoseconds (kubectl --timestamps) -> Unix time."""
    text = re.sub(r"(\.\d{6})\d*", r"\1", text).replace("Z", "+00:00")
    return datetime.fromisoformat(text).timestamp()


def parse_log_line(line: str) -> tuple[float, str, str] | None:
    """(time, logger, message) of a `kubectl logs --timestamps` line, None for other lines."""
    match = LOG_LINE.match(line)
    return (parse_timestamp(match[1]), match[2], match[3]) if match else None


def outages(rows: list[dict], after: float) -> list[dict]:
    """Each stretch of failed requests after time `after`, with the leaders on either side.

    gap is the time from the last 200 before the stretch to the first 200 after it.
    """
    result, last_ok = [], None
    failed = []
    for row in rows:
        ok = int(row["status"]) == 200
        if ok:
            if failed and last_ok is not None:
                result.append({"start": float(last_ok["t"]), "end": float(row["t"]),
                               "gap": float(row["t"]) - float(last_ok["t"]),
                               "failed": len(failed),
                               "status_503": sum(int(r["status"]) == 503 for r in failed),
                               "status_0": sum(int(r["status"]) == 0 for r in failed),
                               "timeouts": sum(r.get("error") == "timeout" for r in failed),
                               "from": last_ok["leader"], "to": row["leader"]})
            failed = []
            last_ok = row
        elif float(row["t"]) >= after or failed:
            failed.append(row)
    return result


def leader_changes(rows: list[dict]) -> list[tuple[float, str, str]]:
    """(time of the first 200 from the new leader, old, new) for every change of leader."""
    changes, current = [], None
    for row in rows:
        if int(row["status"]) == 200:
            if current is not None and row["leader"] != current:
                changes.append((float(row["t"]), current, row["leader"]))
            current = row["leader"]
    return changes


def analyze(meta: dict, rows: list[dict], logs: dict[str, list]) -> dict:
    """The times of one run; logs maps each pod to its [(time, logger, message)]."""
    t_action = meta["t_action"]
    victim = meta["victim"]
    old = victim.rsplit("-", 1)[1]

    detection = election = retake = started = stopped = None
    for pod, entries in sorted(logs.items()):
        if pod == f"{victim}-before":
            for t, _, msg in entries:
                if msg.startswith("stopped;"):
                    stopped = t
            continue
        for t, logger, msg in entries:
            if t < meta["t_action_start"]:
                continue
            if pod == victim:   # the recreated old leader
                if started is None and logger == "fortune.election":
                    started = t
                if retake is None and msg.startswith("NORMAL: coordinator of nodes"):
                    retake = t
                continue
            if detection is None and re.match(rf"-> \w+ to node {old}: no answer", msg):
                detection = t
            if (election is None and detection is not None and t >= detection
                    and msg.startswith("NORMAL: coordinator of nodes")):
                election = t

    all_outages = outages(rows, t_action)
    first = next((o for o in all_outages if o["end"] >= t_action), None)
    served = first["end"] if first else None
    back_from = meta.get("t_restore", t_action)
    return {
        "name": f"{meta['mode']}-run{meta['run']}", "mode": meta["mode"], "victim": victim,
        "detection": detection - t_action if detection else None,
        "election": election - detection if election and detection else None,
        "stopped": stopped - t_action if stopped else None,
        # election done -> first 200 from the new leader: readiness probe + endpoint update
        "routing": served - election if served and election and first["to"] != old else None,
        "gap": first["gap"] if first else 0.0,
        "failed": first["failed"] if first else 0,
        "failed_503": first["status_503"] if first else 0,
        "failed_0": first["status_0"] if first else 0,
        "timeouts": first["timeouts"] if first else 0,
        "new_leader": first["to"] if first else old,
        "back": started - back_from if started else None,
        "retake_log": retake - t_action if retake else None,
        "changes": [(round(t - t_action, 3), a, b) for t, a, b in leader_changes(rows)
                    if t >= t_action],
        "later_outages": [{"at": round(o["start"] - t_action, 3), "gap": round(o["gap"], 3),
                           "failed": o["failed"], "503": o["status_503"], "0": o["status_0"],
                           "from": o["from"], "to": o["to"]}
                          for o in all_outages if o is not first],
        "requests": len(rows),
    }


def fmt(value, unit="s") -> str:
    return "–" if value is None else f"{value:.2f} {unit}".strip()


def summary_line(r: dict) -> str:
    return (f"  {r['name']}: detection {fmt(r['detection'])}, election {fmt(r['election'])}, "
            f"gap {fmt(r['gap'])} ({r['failed']} failed: {r['failed_503']}×503, "
            f"{r['failed_0']}×no answer, of which {r['timeouts']} timeouts), served by node {r['new_leader']}, "
            f"leader changes {r['changes']}")


def stats(values: list) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "–"
    return f"{statistics.fmean(values):.2f} ({min(values):.2f}–{max(values):.2f})"


def cmd_report(args) -> None:
    runs = [run for path in args.json for run in load(path)]
    results = [analyze(*run) for run in runs]
    print("| run | detection s | election s | routing s | gap s | failed (503 / no answer / of which timeouts) | first served by | old pod back after s | leader changes after action (s, from → to) |")
    print("|---|---:|---:|---:|---:|---|---|---:|---|")
    for r in results:
        changes = ", ".join(f"{t:.2f}: {a} → {b}" for t, a, b in r["changes"]) or "none"
        print(f"| {r['name']} | {fmt(r['detection'], '')} | {fmt(r['election'], '')} | "
              f"{fmt(r['routing'], '')} | "
              f"{r['gap']:.2f} | {r['failed']} ({r['failed_503']} / {r['failed_0']} / {r['timeouts']}) | "
              f"node {r['new_leader']} | {fmt(r['back'], '')} | {changes} |")
    print()
    print(f"detection: {stats([r['detection'] for r in results])}  "
          f"election: {stats([r['election'] for r in results])}  "
          f"routing: {stats([r['routing'] for r in results])}  "
          f"gap: {stats([r['gap'] for r in results])}  "
          f"failed: {stats([r['failed'] for r in results])}  "
          f"back: {stats([r['back'] for r in results])}   (mean (min–max))")
    for r in results:
        for o in r["later_outages"]:
            print(f"{r['name']}: next outage at +{o['at']:.2f} s, gap {o['gap']:.2f} s, "
                  f"{o['failed']} failed ({o['503']}×503, {o['0']}×error), node {o['from']} → {o['to']}")
    if args.plot:
        meta, rows, _ = runs[0]
        plot(meta, rows, args.plot)
        print(f"wrote {args.plot}")


def plot(meta: dict, rows: list[dict], png: Path) -> None:
    """One dot per request of one run, colored by outcome, with the action marked."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t0 = meta["t_action"]
    groups = {}
    for row in rows:
        status = int(row["status"])
        key = f"200 from node {row['leader']}" if status == 200 else (
            "503 (follower)" if status == 503 else
            "timeout" if row.get("error") == "timeout" else "no answer (connection error)")
        groups.setdefault(key, []).append((float(row["t"]) - t0, float(row["latency_ms"])))
    colors = {"503 (follower)": "tab:orange", "timeout": "tab:red",
              "no answer (connection error)": "tab:pink",
              "200 from node 3": "tab:blue", "200 from node 2": "tab:green",
              "200 from node 1": "tab:purple"}
    fig, ax = plt.subplots(figsize=(11, 4))
    for key in sorted(groups):
        xs, ys = zip(*groups[key])
        ax.scatter(xs, ys, s=10, label=key, color=colors.get(key))
    ax.axvline(0, color="black", linestyle="--", linewidth=1)
    ax.annotate(f"{meta['mode']} {meta['victim']}", (0, 1), xycoords=("data", "axes fraction"),
                xytext=(4, -12), textcoords="offset points")
    if "t_restore" in meta:
        ax.axvline(meta["t_restore"] - t0, color="gray", linestyle=":", linewidth=1)
        ax.annotate("scale to 3", (meta["t_restore"] - t0, 1), xycoords=("data", "axes fraction"),
                    xytext=(4, -12), textcoords="offset points")
    # zoom in on the action and the leader changes after it
    events = [t - t0 for t, _, _ in leader_changes(rows) if t >= t0] + [meta.get("t_restore", t0) - t0]
    ax.set_xlim(-2, max(events) + 3 if max(events) > 5 else 8)
    ax.set_yscale("log")
    ax.set_xlabel("time since the action (s)")
    ax.set_ylabel("response time (ms, log scale)")
    ax.set_title(f"GET /api/fortune every {meta['interval'] * 1000:.0f} ms during a leader failure")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize="small")
    fig.tight_layout()
    fig.savefig(png, dpi=150)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="take the leader out while polling the site")
    run.add_argument("--mode", choices=["delete", "force", "scale"], default="delete")
    run.add_argument("--runs", type=int, default=1)
    run.add_argument("--url", default="http://localhost:30080/api/fortune")
    run.add_argument("--interval", type=float, default=0.1, help="seconds between requests")
    run.add_argument("--timeout", type=float, default=1.0, help="seconds per request")
    run.add_argument("--before", type=float, default=5.0, help="seconds polled before the action")
    run.add_argument("--after", type=float, default=60.0, help="seconds polled after the action")
    run.add_argument("--restore-after", type=float, default=15.0,
                     help="scale mode: seconds after the action until scaling back to 3")
    run.add_argument("--settle", type=float, default=5.0,
                     help="seconds node 3 must have served before a run starts")
    run.add_argument("--out", type=Path, required=True, help="path prefix of the result files")
    run.set_defaults(func=cmd_run)

    report = sub.add_parser("report", help="timings per run and over all runs")
    report.add_argument("json", type=Path, nargs="+", help="<out>.json file(s) written by run")
    report.add_argument("--plot", type=Path, help="plot the first run to this PNG")
    report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
