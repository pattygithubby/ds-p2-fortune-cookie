"""Experiment 1: load test of GET /api/fortune.

    python loadtest/loadtest.py run --concurrency 1 10 50 --out experiments/results/load.csv
    python loadtest/loadtest.py report experiments/results/load.csv --plot experiments/results/load-cdf.png

`run` does one run per --concurrency value: --requests requests from that many parallel
workers (each worker sends its next request as soon as the previous one is answered) after an
unrecorded warm-up. All runs go into one CSV, one row per request: concurrency, start_s (since
the run's first recorded request), latency_ms, status, leader, pod. A timeout or connection
error is recorded as status 0.

`report` prints one table row per run (requests per second, p50/p95/p99/max latency, error
rate) and plots the latency CDFs in one figure (needs matplotlib, in the dev extras).
"""

import argparse
import asyncio
import csv
import statistics
import sys
import time
from pathlib import Path

import aiohttp

FIELDS = ["concurrency", "start_s", "latency_ms", "status", "leader", "pod"]


async def fetch(session: aiohttp.ClientSession, url: str) -> tuple[int, str, str]:
    """GET url; returns (status, leader, pod), with status 0 for a timeout or network error."""
    try:
        async with session.get(url) as response:
            try:
                body = await response.json(content_type=None)
            except ValueError:
                body = {}
            return response.status, str(body.get("leader", "")), str(body.get("pod", ""))
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return 0, "", ""


async def load(url: str, requests: int, concurrency: int, warmup: int, timeout: float):
    """Run the load test; returns (rows, duration_s) for the recorded requests."""
    connector = aiohttp.TCPConnector(limit=concurrency)
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(connector=connector, timeout=client_timeout) as session:
        for _ in range(warmup):
            await fetch(session, url)

        rows = []
        remaining = requests
        t0 = time.perf_counter()

        async def worker():
            nonlocal remaining
            while remaining > 0:
                remaining -= 1
                start = time.perf_counter()
                status, leader, pod = await fetch(session, url)
                end = time.perf_counter()
                rows.append({"concurrency": concurrency, "start_s": round(start - t0, 6),
                             "latency_ms": round((end - start) * 1000, 3),
                             "status": status, "leader": leader, "pod": pod})

        await asyncio.gather(*(worker() for _ in range(concurrency)))
        duration = time.perf_counter() - t0
    rows.sort(key=lambda row: row["start_s"])
    return rows, duration


def summarize(rows: list[dict], duration: float | None = None) -> dict:
    """Requests per second, latency percentiles (ms, successful requests only), error rate."""
    latencies = [float(row["latency_ms"]) for row in rows if int(row["status"]) == 200]
    errors = sum(1 for row in rows if int(row["status"]) != 200)
    if duration is None:   # from a CSV: first start to last end
        duration = max(float(r["start_s"]) + float(r["latency_ms"]) / 1000 for r in rows) \
            - min(float(r["start_s"]) for r in rows)
    if len(latencies) >= 2:
        q = statistics.quantiles(latencies, n=100, method="inclusive")
        p50, p95, p99 = q[49], q[94], q[98]
    else:
        p50 = p95 = p99 = latencies[0] if latencies else float("nan")
    return {
        "requests": len(rows),
        "rps": len(rows) / duration if duration > 0 else float("nan"),
        "mean": statistics.fmean(latencies) if latencies else float("nan"),
        "p50": p50, "p95": p95, "p99": p99,
        "max": max(latencies, default=float("nan")),
        "error_rate": errors / len(rows) if rows else float("nan"),
        "pods": sorted({row["pod"] for row in rows if row["pod"]}),
    }


TABLE_HEADER = ("| run | requests | req/s | mean ms | p50 ms | p95 ms | p99 ms | max ms | errors | pods |\n"
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")


def table_row(name: str, s: dict) -> str:
    return (f"| {name} | {s['requests']} | {s['rps']:.0f} | {s['mean']:.1f} | {s['p50']:.1f} | "
            f"{s['p95']:.1f} | {s['p99']:.1f} | {s['max']:.1f} | {s['error_rate']:.1%} | "
            f"{', '.join(s['pods'])} |")


def read_runs(path: Path) -> list[tuple[str, list[dict]]]:
    """[(name, rows)] per concurrency level in a CSV written by `run`."""
    runs = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            runs.setdefault(int(row["concurrency"]), []).append(row)
    return [(f"concurrency {c}", rows) for c, rows in sorted(runs.items())]


def cmd_run(args) -> None:
    args.out.parent.mkdir(parents=True, exist_ok=True)
    all_rows = []
    print(TABLE_HEADER)
    for concurrency in args.concurrency:
        rows, duration = asyncio.run(load(args.url, args.requests, concurrency,
                                          args.warmup, args.timeout))
        print(table_row(f"concurrency {concurrency}", summarize(rows, duration)))
        all_rows += rows
    with args.out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"wrote {args.out}")


def cmd_report(args) -> None:
    runs = [run for path in args.csv for run in read_runs(path)]
    print(TABLE_HEADER)
    for name, rows in runs:
        print(table_row(name, summarize(rows)))
    if args.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 4))
        for name, rows in runs:
            latencies = sorted(float(r["latency_ms"]) for r in rows if int(r["status"]) == 200)
            ax.plot(latencies, [(i + 1) / len(latencies) for i in range(len(latencies))],
                    label=name)
        ax.set_xscale("log")
        ax.set_xlabel("response time (ms, log scale)")
        ax.set_ylabel("share of requests answered")
        ax.set_title("GET /api/fortune: response time CDF")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(args.plot, dpi=150)
        print(f"wrote {args.plot}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the load test and write a CSV")
    run.add_argument("--url", default="http://localhost:30080/api/fortune")
    run.add_argument("--requests", type=int, default=10000, help="per run")
    run.add_argument("--concurrency", type=int, nargs="+", default=[1, 10, 50],
                     help="one run per value")
    run.add_argument("--warmup", type=int, default=50, help="unrecorded requests sent first")
    run.add_argument("--timeout", type=float, default=5.0, help="seconds per request")
    run.add_argument("--out", type=Path, required=True)
    run.set_defaults(func=cmd_run)

    report = sub.add_parser("report", help="summarize the runs and plot their latency CDFs")
    report.add_argument("csv", type=Path, nargs="+")
    report.add_argument("--plot", type=Path, help="where to save the CDF figure (PNG)")
    report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
