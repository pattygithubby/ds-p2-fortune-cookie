# Project checklist

Status as of 20 November 2026. Ticked items are done; everything else is still open.
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
- [x] Check that only `bully-3` (node 3) is Ready:
      `kubectl get pods -l app=fortune-cookie` shows `1/1` only for `bully-3`, and
      `kubectl get endpoints fortune-web` lists a single IP
- [x] Check the election in the logs: `kubectl logs bully-3` ends with
      `bully: NORMAL: coordinator of nodes [1, 2, 3]`
- [x] Open the site at the NodePort URL. Don't use `kubectl port-forward`: it attaches to one
      pod and never follows a failover
- [x] Manual failover, tried on kind on 20 November 2026:
  - `kubectl delete pod bully-3`: `bully-2` won the election about 1.1 s after the delete,
    but kind restarted `bully-3` about 2.1 s after the delete and node 3 took over again
    before the readiness probe marked `bully-2` Ready. Clients saw about 2.1 s of failures,
    then node 3. **For experiment 2 this means the delete case measures "detect + restart",
    not a takeover by node 2.**
  - `kubectl scale statefulset bully --replicas=2` (leader stays down): about 3.2 s of
    failures, then `bully-2` (node 2) was the only Ready pod and served everything.
    Scaling back to 3 handed leadership back to node 3.
  - Consider measuring both cases in experiment 2.
- [x] In `CLAUDE.md`, replace "probe is commented out until the endpoint exists" with the
      probe settings above

## 3. Experiment 1: load test

Goal: response times of `GET /api/fortune` under load. All requests go to the single leader pod.
Done on Docker Desktop on 20 November 2026; method, results and findings in
[experiments.md](experiments.md).

- [x] `loadtest/loadtest.py` (Python + aiohttp): `run --url … --requests … --concurrency …
      --out <csv>` writes `start_s, latency_ms, status, leader, pod` per request after 50
      unrecorded warm-up requests; `report` prints the table and plots the CDF
- [x] Ran 10 000 requests at concurrency 1, 10 and 50 (`make loadtest`):
      `experiments/results/load.csv`. 2 000 requests finished in 0.2 s at
      concurrency 50, too short to measure, hence 10 000
- [x] Requests per second, p50/p95/p99/max and error rate per run: about 1 500 / 6 500 /
      8 000 req/s, p50 0.6 / 1.3 / 5.6 ms, no errors, every request served by `bully-3`
- [x] Latency CDF of the three runs: `experiments/results/load-cdf.png` (`matplotlib` added
      to the `dev` extras)
- [x] Setup noted in the README: Docker Desktop Kubernetes v1.36.1, one node, Docker VM with
      8 CPUs and 4 GB on an Apple M1 with 8 GB, replicas = 3, `BULLY_ALGORITHM=improved`

## 4. Experiment 2: leader failure

Goal: how long the election takes, and how long users wait. Done on Docker Desktop on
20 November 2026; method, results and findings in [experiments.md](experiments.md).

- [x] `experiments/failover.py run`: polls `/api/fortune` every 100 ms (1 s timeout) and logs
      `t, latency_ms, status, error, leader, pod`; after 5 s takes the leader out with
      `--mode delete | force | scale`; polls 30 s after the action (the second takeover
      happens within about 5 s, so 60 s wasn't needed); saves `kubectl logs --timestamps` of
      every pod, following the old leader's log from before the action
- [x] Measured from the pod logs: detection (action → `-> … to node 3: no answer`) and election
      (→ `NORMAL: coordinator of nodes [1, 2]`); `failover.py report` does this
- [x] Measured from the client CSV: the user-visible gap and the failed requests (503 vs. no
      answer), plus routing (election → first 200 from node 2)
- [x] 5 runs per mode (`failover-{delete,force,scale}.csv/.json/-pods.log`), mean and min/max reported.
      Delete: detection 1.24 s, election 0.08 s, routing 1.03 s, gap 2.36 s (2.10–2.70)
- [x] The second takeover after `bully-3` restarts: a second gap of 1.0–1.9 s, with 503s from
      `bully-2` while it is still in the Service's endpoints
- [x] Plots: `experiments/results/failover-{delete,force,scale}.png` (run 1 of each mode)
- [ ] Write the measured times into `failover-timeline.drawio` next to the expected limits
- [ ] Optional: repeat with `BULLY_ALGORITHM=original` (set in `statefulset.yaml`, redeploy,
      `make failover RESULTS=experiments/results/original`) and compare election times
      (`make report` reads only `experiments/results/`; for the other folder run
      `make report RESULTS=experiments/results/original`)
- [x] Optional: graceful delete compared with a crash (`--mode force`). The force-deleted pod
      is back after about 1 s instead of 2.7 s, so node 3 usually retakes leadership before
      node 2 is ever routed to: a single gap of about 2.2 s

## 5. Report

- [ ] Find out the required format, page limit and hand-in instructions
- [ ] Export the draw.io diagrams to PNG or SVG (draw.io: File → Export as, or the
      VS Code Draw.io extension)
- [ ] Screenshots of the website: normal, re-electing (open with `?demo`), Chinese style
- [ ] Sections:
  - [ ] Introduction and requirements
  - [ ] Architecture and design decisions: StatefulSet instead of Deployment (stable pod
        names give stable Bully ids: `bully-N` is node N, with `ordinals.start: 1`), headless Service with
        `publishNotReadyAddresses` (followers must be reachable for the election even though
        they are never Ready), readiness probe on `/leader` routing traffic to the leader
        only, followers answering 503
  - [ ] Implementation: reuse of the P1 library unchanged, the thread adapter
        (`election.py`), UDP for the election next to HTTP for the website, the page's retry
  - [ ] Experiment 1: method, results table, CDF plot, discussion (draft material in
        [experiments.md](experiments.md))
  - [ ] Experiment 2: method, results table, timeline plot, discussion (same file)
  - [ ] Limitations
  - [ ] Conclusion
- [ ] Limitations to mention:
  - [ ] Failover time = detection + election + readiness probe + endpoint update, not only
        the election
  - [ ] A restarted `bully-3` causes a second leader change (highest id always wins)
  - [ ] Only the leader serves, so adding replicas adds fault tolerance but no capacity
  - [ ] Reloading the page during a failover shows an error; only fetching a fortune retries
  - [ ] The election uses UDP, which can lose packets; a lost reply looks like a crash
- [ ] Proofread and hand in

## Open questions

- [ ] When is the deadline?
- [x] Which local cluster are we using? Docker Desktop for the experiments (kind also works)
- [ ] Does the report have a required format or page limit?
