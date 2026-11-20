# Leader failure (experiment 2)

[failover.py](failover.py) takes the leader pod out while polling the website like a user,
and measures how long the election takes and how long users wait. Results, findings and the
setup of both experiments are in [docs/experiments.md](../docs/experiments.md). Experiment 1
(the load test) is in [../loadtest/](../loadtest). The data and plots of both are in
[results/](results).

## Run it

With the app deployed (see the main [README](../README.md)) and the `.venv` active:

```sh
make failover   # 5 runs each of delete, force and scale (about 12 minutes), then the report
make report     # only the tables and plots, from the saved results (no cluster needed)
```

`make failover RUNS=3 RESULTS=experiments/results/other` changes the number of runs and the
folder. Results in the same folder are overwritten. One mode at a time:

```sh
python experiments/failover.py run --mode delete --runs 5 --after 30 --out experiments/results/failover-delete
python experiments/failover.py report experiments/results/failover-delete.json --plot experiments/results/failover-delete.png
```

| mode | command | what it models |
|---|---|---|
| `delete` | `kubectl delete pod bully-3` | a graceful stop (SIGTERM); the StatefulSet recreates the pod |
| `force` | `kubectl delete pod bully-3 --grace-period=0 --force` | a crash; the pod is recreated at once |
| `scale` | `kubectl scale statefulset bully --replicas=2`, back to 3 after 15 s | the leader stays down |

How a run works:
- It waits until all pods run and node 3 has served for 5 s.
- It polls `GET /api/fortune` every 100 ms (1 s timeout) over one keep-alive connection.
- After 5 s it takes the leader out, and it keeps polling for 30 s.
- At the end it saves `kubectl logs --timestamps` of every pod. The old leader's log is
  followed from before the action, so its last lines are kept.

`report` reads the files below and computes per run:
- **detection:** the action → the first `-> … to node 3: no answer` in a survivor's log;
- **election:** detection → `NORMAL: coordinator of nodes […]`;
- **routing:** election → the first 200 from the new leader;
- **outage:** the last 200 → the next 200;
- the failed requests, when the old pod came back, and any later outages.

It also prints the mean and min–max over the runs, and plots the first run.

## Files

Per mode in [results/](results). All runs of a mode share these files, and they are
rewritten after every run, so an interrupted series keeps its finished runs.

| file | contents |
|---|---|
| `failover-<mode>.csv` | one row per request: `run, t` (Unix time)`, latency_ms, status, error, leader, pod` |
| `failover-<mode>.json` | `{"runs": [...]}`: settings and action times per run |
| `failover-<mode>-pods.log` | `kubectl logs --timestamps` lines, each prefixed with `run<K> <pod>` (`bully-3-before` = the old leader) |
| `failover-<mode>.png` | run 1, one dot per request |
