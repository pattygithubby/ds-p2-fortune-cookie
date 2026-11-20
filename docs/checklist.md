# Project checklist

Status as of 18 November 2026. Ticked items are done; everything else is still open.
The steps follow the order we planned: app, cluster, the two experiments, report.
Commands assume the repository root and an activated `.venv`
(on Windows: `.venv\Scripts\python.exe` instead of `python`).

## 0. Foundation

- [x] Repository set up from the course template (template code replaced)
- [x] Bully election library from P1 in `src/bully/` (standard library only, UDP port 9000),
      with P1's tests in `tests/bully/`
- [x] Dockerfile (`python:3.12-slim`, `CMD python -m fortune`) and Makefile
- [x] Kubernetes manifests in `deploy/k8s/` (kustomize):
  - StatefulSet `bully`: 3 replicas, `podManagementPolicy: Parallel`, one PVC per pod for the
    Bully state at `/data`
  - headless Service `bully`: `clusterIP: None`, UDP 9000, `publishNotReadyAddresses: true`
  - NodePort Service `fortune-web`: port 80 → container port 8080
- [x] Report diagrams in draw.io (`docs/report/diagrams/`): architecture, failover timeline,
      pod internals, Bully messages
- [ ] If step 2 changes the design (probe settings, fixed NodePort), update
      `architecture.drawio` and `failover-timeline.drawio` to match

## 1. The app

- [x] `election.py`: `LeaderElection` runs `bully.__main__.build()` / `serve()` in a daemon
      thread; `is_leader()` and `leader_id()` read the state vector under `node._lock`
- [x] `fortunes.py`: `data/fortunes.txt` read once into memory (40 fortunes),
      `random.choice()` per request
- [x] `app.py`: `GET /`, `/api/fortune`, `/healthz`, `/leader`, `/static/...`.
      On a follower, `/` and `/api/fortune` answer 503 `{"error", "leader", "pod"}`;
      `/leader` is 200 only on the leader (the readiness probe)
- [x] `__main__.py`: SIGTERM → aiohttp `on_cleanup` → `election.stop()`; access log off;
      log format `HH:MM:SS.mmm logger: message`
- [x] Tests in `tests/fortune/` (aiohttp test client with a fake election; real Bully nodes
      over localhost UDP for the failover test). `python -m pytest`: 193 pass, P1's included
- [x] Ran one pod locally; every endpoint answers correctly
- [x] Frontend designed: SVG cookie, leader badge, night mode, retry during failover
      (3 s request timeout, backoff 250 ms → 1 s, give up after 15 s), `?demo` mode
- [x] **Commit step 1.** Everything above is still uncommitted:
      `git add -A && git commit -m "feat: fortune website with leader-only serving"`
- [x] `README.md`: replace the status line "the website is stubbed" and add the local run
      command (`BULLY_N=1 BULLY_ID=1 BULLY_PEERS=127.0.0.1:9000 BULLY_STATE_DIR=.state python -m fortune`)

## 2. Run it on a cluster

Goal: three pods, one leader, and only the leader receiving web traffic.

- [x] Pick the local cluster: **kind** (`deploy/kind-cluster.yaml`, `make cluster`; maps 30080 to the host). How the image and the NodePort reach it differs per cluster:

  | Cluster | Image into the cluster | Website URL |
  |---|---|---|
  | Docker Desktop (Kubernetes enabled) | nothing, it shares Docker's images | `http://localhost:30080` |
  | kind | `kind load docker-image fortune-cookie` | needs `extraPortMappings` for 30080 when the cluster is created |
  | minikube | `minikube image load fortune-cookie` | `minikube service fortune-web --url` |

- [x] Fix the NodePort so the scripts have a stable URL: in `deploy/k8s/web-service.yaml`
      add `nodePort: 30080` under the `http` port
- [x] Start Docker and build the image: `docker build -t fortune-cookie .`
- [x] Check the clean shutdown: `docker run -d --name fc -e BULLY_N=1 -e BULLY_ID=1 -e BULLY_PEERS=127.0.0.1:9000 fortune-cookie`,
      then `docker stop fc` should finish in about a second (not 10 s) and
      `docker logs fc` should end with `stopped; sent N messages`
- [x] Enable the probes in `deploy/k8s/statefulset.yaml` (replace the commented block):

  ```yaml
  livenessProbe:
    httpGet: {path: /healthz, port: http}
    periodSeconds: 5
  readinessProbe:
    httpGet: {path: /leader, port: http}
    periodSeconds: 1
    failureThreshold: 1   # remove a pod that lost leadership after one failed probe
  ```

- [x] Deploy: `kubectl apply -k deploy/k8s` (`make deploy`). `kubectl rollout status` never
      finishes, because followers are never Ready; use `make status` instead
- [x] Check that only `bully-2` (node 3) is Ready:
      `kubectl get pods -l app=fortune-cookie` shows `1/1` only for `bully-2`, and
      `kubectl get endpoints fortune-web` lists a single IP
- [x] Check the election in the logs: `kubectl logs bully-2` ends with
      `bully: NORMAL: coordinator of nodes [1, 2, 3]`
- [x] Open the site at the NodePort URL. Don't use `kubectl port-forward`: it attaches to one
      pod and never follows a failover
- [x] Manual failover, tried on kind on 20 November 2026:
  - `kubectl delete pod bully-2`: `bully-1` won the election about 1.1 s after the delete,
    but kind restarted `bully-2` about 2.1 s after the delete and node 3 took over again
    before the readiness probe marked `bully-1` Ready. Clients saw about 2.1 s of failures,
    then node 3. **For experiment 2 this means the delete case measures "detect + restart",
    not a takeover by node 2.**
  - `kubectl scale statefulset bully --replicas=2` (leader stays down): about 3.2 s of
    failures, then `bully-1` (node 2) was the only Ready pod and served everything.
    Scaling back to 3 handed leadership back to node 3.
  - Consider measuring both cases in experiment 2.
- [x] In `CLAUDE.md`, replace "probe is commented out until the endpoint exists" with the
      probe settings above

## 3. Experiment 1: load test

Goal: response times of `GET /api/fortune` under load. All requests go to the single leader pod.

- [ ] Write `loadtest/loadtest.py` (Python + aiohttp, already a dependency):
  - arguments: `--url http://localhost:30080/api/fortune --requests 2000 --concurrency 10 --out <csv>`
  - one CSV row per request: `start_s, latency_ms, status, leader, pod`
  - a short warm-up (e.g. 50 requests) that is not recorded
- [ ] Run it at concurrency 1, 10 and 50 and save `experiments/results/load-c{1,10,50}.csv`
- [ ] Per run, compute: requests per second, p50, p95, p99, max latency, and error rate
      (share of non-200 responses). `statistics.quantiles(latencies, n=100)` gives the
      percentiles
- [ ] Plot the latency CDF of the three runs in one figure (add `matplotlib` to the `dev`
      extras in `pyproject.toml`) and save it as `experiments/results/load-cdf.png`
- [ ] Note the setup in the report: cluster type, CPU/RAM, replicas = 3, `BULLY_ALGORITHM`

## 4. Experiment 2: leader failure

Goal: how long the election takes, and how long users wait.

- [ ] Write `experiments/failover.py`:
  - poll `/api/fortune` every 100 ms with a 1 s timeout; log `t, status, leader, pod` to CSV
    (a timeout or connection error is logged as status `0`)
  - after 5 s, take the leader's pod name from the last response and run
    `kubectl delete pod <pod>` with `subprocess`; log the time of the delete
  - keep polling for about 60 s, so the second takeover is recorded too
  - finally save `kubectl logs --timestamps <pod>` of every pod, so the server log times
    can be lined up with the client times
- [ ] Measure from the pod logs (on the node that wins, e.g. `bully-1`):
  - detection: delete → `-> AreYouThere to node 3: no answer`
  - election: detection → `NORMAL: coordinator of nodes [1, 2]`
  - expected limits: detection ≤ check interval (2 s) + T (1 s); election ≈ T + 2 round trips
- [ ] Measure from the client CSV:
  - user-visible gap: last 200 from node 3 → first 200 from node 2
  - number of failed requests (status 0 or 503)
- [ ] Repeat 5 times (`failover-run{1..5}.csv`); report the mean and min/max of each time
- [ ] Describe the second takeover after `bully-2` restarts: its timing, and whether any
      503s appear while `bully-1` is still in the Service's endpoints
- [ ] Plot one run: time on the x axis, one dot per request, colored by status/leader, with
      the delete marked; save as `experiments/results/failover-run1.png`
- [ ] Write the measured times into `failover-timeline.drawio` next to the expected limits
- [ ] Optional: repeat with `BULLY_ALGORITHM=original` (set in `statefulset.yaml`, redeploy)
      and compare election times
- [ ] Optional: compare a graceful delete with a crash
      (`kubectl delete pod bully-2 --grace-period=0 --force`)

## 5. Report

- [ ] Find out the required format, page limit and hand-in instructions
- [ ] Export the draw.io diagrams to PNG or SVG (draw.io: File → Export as, or the
      VS Code Draw.io extension)
- [ ] Screenshots of the website: normal, re-electing (open with `?demo`), Chinese style
- [ ] Sections:
  - [ ] Introduction and requirements
  - [ ] Architecture and design decisions: StatefulSet instead of Deployment (stable pod
        names give stable Bully ids: `bully-N` is node N+1), headless Service with
        `publishNotReadyAddresses` (followers must be reachable for the election even though
        they are never Ready), readiness probe on `/leader` routing traffic to the leader
        only, followers answering 503
  - [ ] Implementation: reuse of the P1 library unchanged, the thread adapter
        (`election.py`), UDP for the election next to HTTP for the website, the page's retry
  - [ ] Experiment 1: method, results table, CDF plot, discussion
  - [ ] Experiment 2: method, results table, timeline plot, discussion
  - [ ] Limitations
  - [ ] Conclusion
- [ ] Limitations to mention:
  - [ ] Failover time = detection + election + readiness probe + endpoint update, not only
        the election
  - [ ] A restarted `bully-2` causes a second leader change (highest id always wins)
  - [ ] Only the leader serves, so adding replicas adds fault tolerance but no capacity
  - [ ] Reloading the page during a failover shows an error; only fetching a fortune retries
  - [ ] The election uses UDP, which can lose packets; a lost reply looks like a crash
- [ ] Proofread and hand in

## Open questions

- [ ] When is the deadline?
- [ ] Which local cluster are we using?
- [ ] Does the report have a required format or page limit?
