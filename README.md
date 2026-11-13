# Fortune cookie on Kubernetes

A fortune cookie website hosted on Kubernetes. The pods elect a leader with the Bully
algorithm (from our P1 project), and only the leader serves the website. If the leader
fails, the others elect a new one. The assignment is in [docs/assignment.md](docs/assignment.md).

> Status: scaffolding. The election library and its tests work; the website is stubbed.

## Layout

| Path | Contents |
|---|---|
| [src/bully/](src/bully) | Bully election library from P1 (standard library only) |
| [src/fortune/](src/fortune) | The website: config, election adapter, fortune source, aiohttp app and static page |
| [tests/](tests) | `tests/bully` (P1's tests) and `tests/fortune` |
| [deploy/k8s/](deploy/k8s) | StatefulSet, headless Service for the election, web Service for users |
| [loadtest/](loadtest), [experiments/](experiments) | The two experiments for the report |
| [docs/](docs) | Assignment, Bully paper notes, report |

## Setup

Needs Python 3.12+. Create a virtual environment once, and activate it in every new terminal:

```sh
python3 -m venv .venv
source .venv/bin/activate
make install   # pip install -e '.[dev]'
```

## Commands

```sh
make install   # pip install -e '.[dev]'  (inside the activated .venv)
make test      # run all tests
make build     # docker build -t fortune-cookie .
make deploy    # kubectl apply -k deploy/k8s
```
