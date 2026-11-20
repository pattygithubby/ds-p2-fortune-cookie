# Load test (experiment 1)

[loadtest.py](loadtest.py) sends many `GET /api/fortune` requests to the `fortune-web`
Service and records each response time. Results, findings and the setup are in
[docs/experiments.md](../docs/experiments.md); the data is in
[../experiments/results/](../experiments/results).

## Run it

With the app deployed (see the main [README](../README.md)) and the `.venv` active:

```sh
make loadtest   # 10 000 requests each at concurrency 1, 10 and 50 (about a minute), then the plot
```

or directly:

```sh
python loadtest/loadtest.py run --concurrency 1 10 50 --requests 10000 --out experiments/results/load.csv
python loadtest/loadtest.py report experiments/results/load.csv --plot experiments/results/load-cdf.png
```

`run` does one run per `--concurrency` value. Each of that many workers sends its next request
as soon as the previous one is answered (a closed loop), after 50 warm-up requests that are not
recorded. All runs go into one CSV with one row per request:
`concurrency, start_s, latency_ms, status, leader, pod` (status 0 = timeout or network error).
`report` prints requests per second, p50/p95/p99/max of the successful requests and the error
rate per run, and plots the response-time CDFs.
