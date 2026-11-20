# Fortune cookie on Kubernetes

A fortune cookie website hosted on Kubernetes. The pods elect a leader with the Bully
algorithm (from our P1 project), and only the leader serves the website. If the leader
fails, the others elect a new one. The assignment is in [docs/assignment.md](docs/assignment.md).

> Status: the website and the election run on Kubernetes, tested on Docker Desktop and kind
> (3 pods, only the leader serves, failover works). The two experiments and the report are
> still to do. See
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

Needs Docker, `kubectl`, and a local Kubernetes cluster (1.28 or newer). Pick one of the two
below; everything after "Check that it works" is the same for both. The `make` targets are
shown with the commands they run, so you can type those directly if you don't have `make`
(e.g. on Windows).

### Option A: Docker Desktop

Once: in Docker Desktop open **Settings → Kubernetes**, tick **Enable Kubernetes** (choose
**kubeadm** if it asks for a cluster type), click **Apply & restart**, and wait until
Kubernetes shows green in the bottom-left corner.

```sh
kubectl config use-context docker-desktop   # make kubectl talk to Docker Desktop
make build     # docker build -t fortune-cookie .
make deploy    # kubectl apply -k deploy/k8s
```

Docker Desktop's Kubernetes uses your locally built image directly, so skip `make cluster`
and `make load` (those are for kind). Quitting Docker Desktop stops the cluster; the pods come
back when you start it again.

### Option B: kind

[kind](https://kind.sigs.k8s.io/) runs a Kubernetes cluster inside a Docker container
(`brew install kind`, or see the kind docs for Windows/Linux).

```sh
make build     # docker build -t fortune-cookie .
make cluster   # kind create cluster --config deploy/kind-cluster.yaml   (skipped if it exists)
make load      # kind load docker-image fortune-cookie --name fortune
make deploy    # kubectl apply -k deploy/k8s
```

`make cluster` also switches kubectl to the kind cluster (`kind-fortune`). Docker Desktop's
Kubernetes and kind both use `localhost:30080`, so run only one of them at a time.

### Check that it works

```sh
make status    # pods and the web Service's endpoint
```

Open http://localhost:30080. After about 10 s, `make status` should show only `bully-3` as
`1/1` Ready, the other two `0/1`, and `fortune-web` with a single endpoint. Followers that are
`0/1` are expected: they fail the `/leader` probe on purpose. This also means
`kubectl rollout status statefulset/bully` never finishes, so don't wait on it.

Pod `bully-N` is Bully node N, so `bully-3` (node 3) is the leader when all pods are up.

```sh
kubectl logs bully-3                        # ends with "bully: NORMAL: coordinator of nodes [1, 2, 3]"
kubectl logs -f bully-2                     # follow a node's view of the election
kubectl get pods -l app=fortune-cookie -w   # live pod status (Ctrl+C to stop)
```

Use the NodePort URL, not `kubectl port-forward`: port-forward sticks to one pod and doesn't
follow a failover.

### Stop a node

There are two ways, and they show different things:

- **A node crashes and comes back:** `kubectl delete pod bully-N` (any node). The pod stops at
  once and Kubernetes recreates it under the same name about 2 s later.
  - Leader (`kubectl delete pod bully-3`): `bully-2` (node 2) notices within about a second
    and becomes leader, but `bully-3` is back before the Service switches to `bully-2`, and
    node 3 takes over again. Users see about 2 s of failed requests (the page shows
    "Electing a new leader… retry n") and then node 3 again. `kubectl logs bully-2` shows the
    short-lived election.
  - Follower (`bully-1` or `bully-2`): users notice nothing; `kubectl logs -f bully-3` shows
    the leader finding the node missing and the node rejoining.
- **A node stays down:** scale the StatefulSet down. This always removes the highest-numbered
  pods, so it can keep `bully-3` (or `bully-3` and `bully-2`) down, but not `bully-1` or
  `bully-2` alone.

  ```sh
  kubectl scale statefulset bully --replicas=2   # stops bully-3: about 3 s later bully-2 serves
  kubectl scale statefulset bully --replicas=1   # also stops bully-2: bully-1 serves
  kubectl scale statefulset bully --replicas=3   # brings them back; bully-3 takes over again
  ```

  `BULLY_N` stays 3, so the remaining nodes treat the missing ones as crashed.

Sending a signal from inside a pod (e.g. `kubectl exec bully-2 -- kill -STOP 1`) does not
work: the app is process 1 in its container, and Linux ignores such signals for process 1.

### Change the code

After a code change, rebuild and restart the pods:

```sh
make build redeploy        # Docker Desktop
make build load redeploy   # kind
```

`redeploy` is `kubectl delete pod -l app=fortune-cookie`. Don't rely on
`kubectl rollout restart` or a changed image tag: a StatefulSet rolling update waits for each
new pod to become Ready, so it stalls at the first follower.

### Clean up

```sh
make undeploy         # remove the Services, StatefulSet and the pods' state volumes
make cluster-delete   # kind only: delete the kind cluster
```

On Docker Desktop you can also untick **Enable Kubernetes** to stop the cluster for good.

### Other clusters

The StatefulSet numbers its pods from 1 (`ordinals.start`) and reads each pod's number from
the `apps.kubernetes.io/pod-index` label, which needs Kubernetes 1.28 or newer. With minikube,
use `minikube image load fortune-cookie` instead of `make load`, and
`minikube service fortune-web --url` for the address.

## Commands

```sh
make install          # pip install -e '.[dev]'  (inside the activated .venv)
make test             # run all tests
make build            # docker build -t fortune-cookie .
make cluster          # create the kind cluster "fortune" (kind only)
make load             # copy the image into the kind cluster (kind only)
make deploy           # kubectl apply -k deploy/k8s
make status           # pods and the leader endpoint
make redeploy         # restart all pods (after make build, and make load on kind)
make undeploy         # remove the deployment and its volumes
make cluster-delete   # delete the kind cluster (kind only)
```
