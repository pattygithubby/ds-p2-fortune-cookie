# Fortune cookie on Kubernetes

A fortune cookie website hosted on Kubernetes. The pods elect a leader with the Bully
algorithm (from our P1 project), and only the leader serves the website. If the leader
fails, the others elect a new one. The assignment is in [docs/assignment.md](docs/assignment.md).

> Status: the website and the election run on a local kind cluster (3 pods, only the leader
> serves, failover works). The two experiments and the report are still to do. See
> [docs/checklist.md](docs/checklist.md).

## Layout

| Path | Contents |
|---|---|
| [src/bully/](src/bully) | Bully election library from P1 (standard library only, UDP port 9000) |
| [src/fortune/](src/fortune) | The website: config, election adapter, fortune source, aiohttp app and static page |
| [tests/](tests) | `tests/bully` (P1's tests) and `tests/fortune` |
| [deploy/k8s/](deploy/k8s) | StatefulSet, headless Service for the election, web Service for users |
| [deploy/kind-cluster.yaml](deploy/kind-cluster.yaml) | Local kind cluster that exposes the site on `localhost:30080` |
| [loadtest/](loadtest), [experiments/](experiments) | The two experiments for the report (not written yet) |
| [docs/](docs) | Assignment, Bully paper notes, checklist, report diagrams (`docs/report/diagrams/`) |

## How it works

Every pod runs the same app: a Bully node (UDP 9000) in a background thread and an aiohttp
web server (port 8080). Pod `bully-N` of the StatefulSet is Bully node N (pods are numbered from 1), so
`bully-3` (node 3) leads when all three pods are up.

| Route | Leader | Follower |
|---|---|---|
| `GET /` | the page | 503 |
| `GET /api/fortune` | `{"fortune", "leader", "pod"}` | 503 `{"error", "leader", "pod"}` |
| `GET /leader` | 200 | 503 (readiness probe: only the leader gets traffic) |
| `GET /healthz` | 200 | 200 (liveness probe) |

On Kubernetes, each pod has a readiness probe on `/leader`, so only the leader is Ready and
the `fortune-web` Service (NodePort 30080) sends all traffic to it. The headless Service
`bully` gives the pods their election addresses (`bully-N.bully:9000`) and keeps
followers reachable even though they are never Ready.

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

## Run it on Kubernetes

Needs Docker (Docker Desktop is fine), `kubectl`, and [kind](https://kind.sigs.k8s.io/)
(`brew install kind`, or see the kind docs for Windows/Linux). kind runs a Kubernetes cluster
inside a Docker container. The `make` targets are shown with the commands they run, so you can
type those directly on Windows if you don't have `make`.

```sh
make build     # docker build -t fortune-cookie .
make cluster   # kind create cluster --config deploy/kind-cluster.yaml   (skipped if it exists)
make load      # kind load docker-image fortune-cookie --name fortune
make deploy    # kubectl apply -k deploy/k8s
make status    # pods and the web Service's endpoint
```

Open http://localhost:30080. After about 10 s, `make status` should show only `bully-3` as
`1/1` Ready, the other two `0/1`, and `fortune-web` with a single endpoint. Followers that are
`0/1` are expected: they fail the `/leader` probe on purpose. This also means
`kubectl rollout status statefulset/bully` never finishes, so don't wait on it.

```sh
kubectl logs bully-3      # ends with "bully: NORMAL: coordinator of nodes [1, 2, 3]"
kubectl logs -f bully-2   # follow a follower's view of the election
```

Use the NodePort URL, not `kubectl port-forward`: port-forward sticks to one pod and doesn't
follow a failover.

### Kill the leader

There are two ways, and they show different things:

- **Leader crashes and comes back:** `kubectl delete pod bully-3`. `bully-2` (node 2) notices
  within about a second and becomes leader, but Kubernetes restarts `bully-3` about 2 s after
  the delete, and node 3 takes over again before the Service switches to `bully-2`. Users see
  about 2 s of failed requests (the page shows "Electing a new leader… retry n") and then node 3
  again. `kubectl logs bully-2` shows the short-lived election.
- **Leader stays down:** `kubectl scale statefulset bully --replicas=2` removes `bully-3`.
  About 3 s later `bully-2` is the only Ready pod and the page's badge shows node 2.
  `kubectl scale statefulset bully --replicas=3` brings `bully-3` back, and it takes over again.
  (`BULLY_N` stays 3, so the nodes keep treating node 3 as a member that is down.)

### Change the code

After a code change, rebuild, load and restart the pods:

```sh
make build load redeploy   # redeploy = kubectl delete pod -l app=fortune-cookie
```

Don't rely on `kubectl rollout restart` or a changed image tag: a StatefulSet rolling update
waits for each new pod to become Ready, so it stalls at the first follower.

### Clean up

```sh
make undeploy         # remove the Services, StatefulSet and the pods' state volumes
make cluster-delete   # delete the kind cluster
```

### Other clusters

Any cluster needs Kubernetes 1.28 or newer: the StatefulSet numbers its pods from 1
(`ordinals.start`) and reads each pod's number from the `apps.kubernetes.io/pod-index` label.

With Docker Desktop's built-in Kubernetes (Settings → Kubernetes → Enable, kubeadm mode),
skip `make cluster` and `make load`: it uses Docker's images directly, and the site is at
http://localhost:30080. With minikube, use `minikube image load fortune-cookie` instead of
`make load`, and `minikube service fortune-web --url` for the address.

## Commands

```sh
make install          # pip install -e '.[dev]'  (inside the activated .venv)
make test             # run all tests
make build            # docker build -t fortune-cookie .
make cluster          # create the kind cluster "fortune"
make load             # copy the image into the kind cluster
make deploy           # kubectl apply -k deploy/k8s
make status           # pods and the leader endpoint
make redeploy         # restart all pods (after make build load)
make undeploy         # remove the deployment and its volumes
make cluster-delete   # delete the kind cluster
```
