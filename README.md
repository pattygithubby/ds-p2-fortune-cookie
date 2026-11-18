# Fortune cookie on Kubernetes

A fortune cookie website hosted on Kubernetes. The pods elect a leader with the Bully
algorithm (from our P1 project), and only the leader serves the website. If the leader
fails, the others elect a new one. The assignment is in [docs/assignment.md](docs/assignment.md).

> Status: the website and the election work and are tested locally. Not yet run on a cluster;
> the two experiments and the report are still to do. See [docs/checklist.md](docs/checklist.md).

## Layout

| Path | Contents |
|---|---|
| [src/bully/](src/bully) | Bully election library from P1 (standard library only, UDP port 9000) |
| [src/fortune/](src/fortune) | The website: config, election adapter, fortune source, aiohttp app and static page |
| [tests/](tests) | `tests/bully` (P1's tests) and `tests/fortune` |
| [deploy/k8s/](deploy/k8s) | StatefulSet, headless Service for the election, web Service for users |
| [loadtest/](loadtest), [experiments/](experiments) | The two experiments for the report (not written yet) |
| [docs/](docs) | Assignment, Bully paper notes, checklist, report diagrams (`docs/report/diagrams/`) |

## How it works

Every pod runs the same app: a Bully node (UDP 9000) in a background thread and an aiohttp
web server (port 8080). Pod `bully-N` of the StatefulSet is Bully node N+1, so `bully-2`
(node 3) leads when all three pods are up.

| Route | Leader | Follower |
|---|---|---|
| `GET /` | the page | 503 |
| `GET /api/fortune` | `{"fortune", "leader", "pod"}` | 503 `{"error", "leader", "pod"}` |
| `GET /leader` | 200 | 503 (readiness probe: only the leader gets traffic) |
| `GET /healthz` | 200 | 200 (liveness probe) |

The page retries failed requests for up to 15 s, so a failover shows as a short wait.
Open it with `?demo` to use a built-in fake API that simulates failovers.

## Setup

Needs Python 3.12+. Create a virtual environment once, and activate it in every new terminal:

```sh
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
make install                   # pip install -e '.[dev]'
```

## Run one pod locally

A single node elects itself leader. Then open http://localhost:8080.

```sh
# bash
BULLY_N=1 BULLY_ID=1 BULLY_PEERS=127.0.0.1:9000 BULLY_STATE_DIR=.state python -m fortune
```

```powershell
# PowerShell
$env:BULLY_N="1"; $env:BULLY_ID="1"; $env:BULLY_PEERS="127.0.0.1:9000"; $env:BULLY_STATE_DIR=".state"
python -m fortune
```

The `BULLY_*` variables are documented in [src/bully/\_\_main\_\_.py](src/bully/__main__.py);
`WEB_PORT` (default 8080) and `LOG_LEVEL` in [src/fortune/config.py](src/fortune/config.py).

## Commands

```sh
make install   # pip install -e '.[dev]'  (inside the activated .venv)
make test      # run all tests
make build     # docker build -t fortune-cookie .
make deploy    # kubectl apply -k deploy/k8s
```
