# CLAUDE.md

Guidance for Claude Code when working in this repository. The full assignment text is in [docs/assignment.md](docs/assignment.md).

## Project

A fortune cookie website hosted on Kubernetes. Multiple pods run the same app and use the **Bully algorithm** to elect a leader pod; the leader serves the website. If the leader fails, the remaining pods must elect a new one via the algorithm.

Started from the template at https://github.com/thecml/bully-in-kubernetes; the template code has been replaced (see below).

## Requirements

The solution must include at least:

- A deployment specification that supports multiple pods.
- An active Bully algorithm that elects a new leader when the current one fails.
- A website that shows the fortune cookie text and has a way to get another one (a simple HTML page with some CSS and a bit of JavaScript is enough).

Fortunes can be stored in memory, in a file, or fetched from the Internet.

The report must explain design decisions and implementation, and include two experiments:

1. **Load test** — send many HTTP requests rapidly to the cluster endpoint (e.g. a PowerShell or NodeJS loop) and record response times.
2. **Leader failure** — shut down the leader pod and document how a new leader is elected: how long it takes, and whether users notice any lag.

## Repository layout

`src/` layout, two packages that only meet in one adapter:

- [src/bully/](src/bully) — the Bully election library, copied unchanged from our P1 project (`ds-p1-bully-election`). Standard library only, Python 3.12+. Has the original Garcia-Molina algorithm ([original.py](src/bully/original.py)) and our improved variant with fewer messages ([improved.py](src/bully/improved.py)), chosen with `BULLY_ALGORITHM` (default and recommended: `improved`). Nodes talk over UDP port 9000. On Kubernetes, pod `bully-N` is node N: the StatefulSet numbers pods from 1 (`ordinals.start: 1`) and sets `BULLY_ID` from the `apps.kubernetes.io/pod-index` label, because the library on its own would read the host name as ordinal + 1. [\_\_main\_\_.py](src/bully/__main__.py) has `Config.from_env`, `build()` and `serve()` and documents the `BULLY_*` variables. The algorithm is described in [docs/bully-ref.md](docs/bully-ref.md). Treat it as a library: don't put website code in it.
- [src/fortune/](src/fortune) — the website (aiohttp). Only the leader hosts it: on a follower `/` and `/api/fortune` answer 503 with the leader's id, and the page's JavaScript retries, so a failover shows up as a short wait.
  - [config.py](src/fortune/config.py) — web settings from the environment (`WEB_PORT`, `LOG_LEVEL`).
  - [election.py](src/fortune/election.py) — `LeaderElection`, the only module that imports `bully`: runs `bully.__main__.build()` / `serve()` in a daemon thread and exposes `is_leader()` (state `NORMAL` and coordinator is self) / `leader_id()`, both read under `node._lock`.
  - [fortunes.py](src/fortune/fortunes.py) — `FortuneSource`, reads [data/fortunes.txt](src/fortune/data/fortunes.txt) once into memory.
  - [web/app.py](src/fortune/web/app.py) — `create_app(fortunes, election)`. `/` and `/api/fortune` are leader-only; `/leader` is 200 only on the leader (readiness probe); `/healthz` is always 200 (liveness); `/static/*` is served by any pod. Responses are `Cache-Control: no-store`. Follower 503s also close the connection (`force_close()`): a Service picks a pod only when a connection opens, so without this a keep-alive browser stays stuck on a pod that lost leadership (seen after scaling 2 → 3).
  - [web/static/](src/fortune/web/static) — plain HTML/CSS/JS page. `app.js` retries through a failover (3 s request timeout, backoff 250 ms → 1 s, gives up after 15 s). Open with `?demo` for a fake API that simulates failovers without a server.
  - [\_\_main\_\_.py](src/fortune/__main__.py) — `python -m fortune`, the container entry point. SIGTERM → aiohttp `on_cleanup` → `election.stop()`. Access log is off; log lines have millisecond timestamps, which experiment 2 measures from.
- [tests/bully/](tests/bully) — P1's tests (keep them passing). [tests/fortune/](tests/fortune) — tests for the website.
- [deploy/k8s/](deploy/k8s) — kustomize: StatefulSet `bully` (3 replicas, `podManagementPolicy: Parallel`, a 10Mi PVC per pod at `/data` for the Bully safe storage; `BULLY_N` must equal `replicas`), headless Service `bully` (UDP 9000, gives each pod the DNS name `bully-N.bully`, and `BULLY_PEERS` is `bully-{id}.bully:9000`; `publishNotReadyAddresses: true` so followers, which are never Ready, stay reachable), and NodePort Service `fortune-web` (port 80 → 8080).
  - NodePort fixed at **30080**. Probes: liveness `/healthz` (every 5 s), readiness `/leader` (every 1 s, `failureThreshold: 1`), so only the leader is Ready and `fortune-web` has a single endpoint. Followers showing `0/1` is intended, and `kubectl rollout status` never completes.
  - A StatefulSet rolling update stalls at the first follower (it waits for each pod to become Ready). Redeploy by deleting the pods (`make redeploy`), not with `kubectl rollout restart`.
- [deploy/kind-cluster.yaml](deploy/kind-cluster.yaml) — the local kind cluster `fortune`, mapping NodePort 30080 to `localhost:30080`.
- [loadtest/](loadtest), [experiments/](experiments) — the two report experiments (placeholders; plans in [docs/checklist.md](docs/checklist.md) steps 3–4).
- [docs/](docs) — assignment, Bully paper notes, [checklist.md](docs/checklist.md) (project status and next steps), `report/` (draw.io diagrams in `report/diagrams/`).

## Failover behaviour

Pod `bully-3` (node 3) leads when all pods are up. When the leader dies, the followers notice on their next `timeout()` (every `CHECK_INTERVAL` = 2 s, plus T = 1 s with no answer), elect `bully-2` (node 2), and it starts passing `/leader`. The StatefulSet then recreates `bully-3` with the same name and volume; its `recovery()` always starts an election, so node 3 takes leadership back.

Measured on kind (20 November 2026): after `kubectl delete pod bully-3`, the pod is back about 2 s later, before the 1 s readiness probe marks `bully-2` Ready, so node 2 never serves and clients see about 2 s of failures. To show a takeover that lasts, keep the leader down with `kubectl scale statefulset bully --replicas=2` (about 3 s of failures, then `bully-2` serves); scale back to 3 afterwards.

## Build and run

Dependencies live in a gitignored `.venv` (`python3 -m venv .venv`, then `source .venv/bin/activate`). Activate it before running anything; the system Python has no `aiohttp`.

```sh
make install   # pip install -e '.[dev]'
make test      # python3 -m pytest (pytest finds src/ via pythonpath in pyproject.toml)
make build     # docker build -t fortune-cookie .
make deploy    # kubectl apply -k deploy/k8s
```

Cluster workflow (kind; full steps in [README.md](README.md)): `make build cluster load deploy`, then `make status`; site at http://localhost:30080. After code changes: `make build load redeploy`. Tear down: `make undeploy` (also deletes the state PVCs) and `make cluster-delete`.

To run one pod locally (it elects itself leader): `BULLY_N=1 BULLY_ID=1 BULLY_PEERS=127.0.0.1:9000 BULLY_STATE_DIR=.state python -m fortune`, then open http://localhost:8080. On Windows the venv's interpreter is `.venv/Scripts/python.exe`.

The StatefulSet uses a local image (`imagePullPolicy: IfNotPresent`); load it into the cluster first (e.g. `kind load docker-image fortune-cookie`). To use Docker Hub instead, change the image and pull policy (https://kubernetes.io/docs/concepts/containers/images/).

## Useful references

- Headless Services: https://kubernetes.io/docs/concepts/services-networking/service/#headless-services
- StatefulSets (stable pod names/IDs, may suit Bully better than a Deployment): https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/
- aiohttp: https://docs.aiohttp.org/en/stable/index.html
- Kubernetes Python client: https://github.com/kubernetes-client/python
