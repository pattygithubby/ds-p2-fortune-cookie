# CLAUDE.md

Guidance for Claude Code when working in this repository. The full assignment text is in [docs/assignment.md](docs/assignment.md).

## Project

A fortune cookie website hosted on Kubernetes. Multiple pods run the same app and use the **Bully algorithm** to elect a leader pod; the leader serves the website. If the leader fails, the remaining pods must elect a new one via the algorithm.

Started from the template at https://github.com/thecml/bully-in-kubernetes.

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

- [bully/](bully) — the Bully election package, copied from our P1 project (`ds-p1-bully-election`). Standard library only, Python 3.12+. Contains the original Garcia-Molina algorithm ([original.py](bully/original.py)) and our improved variant with fewer messages ([improved.py](bully/improved.py)), selected with `BULLY_ALGORITHM` (default `improved`). Nodes talk over UDP port 9000. On Kubernetes the node id comes from the StatefulSet pod name (`bully-0` is node 1). [\_\_main\_\_.py](bully/__main__.py) shows the run loop and the `BULLY_*` environment variables. The algorithm is described in [docs/bully-ref.md](docs/bully-ref.md).
- [tests/](tests) — P1's tests for the package (`python3 -m pytest`, about 12 s). Keep them passing if `bully/` changes.
- [app.py](app.py) — still the unchanged template: aiohttp server and a placeholder Bully task. It is not wired to `bully/` yet.
- [k8s/deployment.yaml](k8s/deployment.yaml) — Deployment (`bully-app`, 2 replicas, local image, `imagePullPolicy: Never`). Injects `WEB_PORT=8080` and `POD_IP` (from `status.podIP`).
- [k8s/headless-service.yaml](k8s/headless-service.yaml) — headless Service `bully-service` (`clusterIP: None`, port 80 → 8080), used for pod discovery.
- [Dockerfile](Dockerfile) — Python 3.12 image, runs `app.py`, exposes 8080.
- [requirements.txt](requirements.txt) — `aiohttp`, `requests`.

## How the template works

- Each pod picks a random `POD_ID` (0–100) at startup and reads its own IP from `POD_IP`.
- `run_bully()` runs periodically: it does a DNS lookup on `bully-service` to get all pod IPs, removes its own IP, then calls `GET /pod_id` on each other pod and stores the IDs in a dict.
- Endpoints: `GET /pod_id` (implemented), and stubs for `POST /receive_election`, `POST /receive_answer`, `POST /receive_coordinator` — the Bully algorithm goes here.
- Peer requests currently use the synchronous `requests` library, which blocks the event loop. Prefer `aiohttp.ClientSession` for async requests (https://docs.aiohttp.org/en/stable/client_quickstart.html).

## Build and run

```sh
docker build -t bully-app .
kubectl apply -f k8s/headless-service.yaml
kubectl apply -f k8s/deployment.yaml
```

The deployment uses a local image. To use Docker Hub instead, change the image and set it to pull on every deploy (https://kubernetes.io/docs/concepts/containers/images/).

## Useful references

- Headless Services: https://kubernetes.io/docs/concepts/services-networking/service/#headless-services
- StatefulSets (stable pod names/IDs, may suit Bully better than a Deployment): https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/
- aiohttp: https://docs.aiohttp.org/en/stable/index.html
- Kubernetes Python client: https://github.com/kubernetes-client/python
