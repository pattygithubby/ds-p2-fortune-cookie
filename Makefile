IMAGE ?= fortune-cookie
CLUSTER ?= fortune

.PHONY: install test build cluster load deploy redeploy status undeploy cluster-delete loadtest failover report clean

install:        ## install the package and dev tools into the current environment
	pip install -e '.[dev]'

test:           ## run all tests
	python3 -m pytest

build:          ## build the container image
	docker build -t $(IMAGE) .

cluster:        ## create the local kind cluster if it doesn't exist (site at http://localhost:30080)
	@if kind get clusters 2>/dev/null | grep -qx '$(CLUSTER)'; then \
		echo "kind cluster '$(CLUSTER)' already exists, using it"; \
		kubectl config use-context kind-$(CLUSTER); \
	else \
		kind create cluster --config deploy/kind-cluster.yaml; \
	fi

load:           ## copy the image into the kind cluster (not needed on Docker Desktop Kubernetes)
	kind load docker-image $(IMAGE) --name $(CLUSTER)

deploy:         ## apply the Kubernetes manifests
	kubectl apply -k deploy/k8s

redeploy:       ## restart all pods so they pick up a newly built/loaded image
	kubectl delete pod -l app=fortune-cookie

status:         ## pods (only the leader is Ready) and the web Service's endpoint
	kubectl get pods -l app=fortune-cookie -o wide
	kubectl get endpoints fortune-web

undeploy:       ## remove everything deploy created, including the Bully state volumes
	kubectl delete -k deploy/k8s
	kubectl delete pvc -l app=fortune-cookie

cluster-delete: ## delete the kind cluster
	kind delete cluster --name $(CLUSTER)

RESULTS ?= experiments/results
RUNS ?= 5

loadtest:       ## experiment 1: 10000 requests at concurrency 1, 10 and 50, then the plot
	python3 loadtest/loadtest.py run --concurrency 1 10 50 --out $(RESULTS)/load.csv
	python3 loadtest/loadtest.py report $(RESULTS)/load.csv --plot $(RESULTS)/load-cdf.png

failover:       ## experiment 2: RUNS leader failures per mode (delete, force, scale), then the report
	for m in delete force scale; do \
		python3 experiments/failover.py run --mode $$m --runs $(RUNS) --after 30 --out $(RESULTS)/failover-$$m || exit 1; \
	done
	$(MAKE) report

report:         ## print the tables and redraw the plots from the saved results
	python3 loadtest/loadtest.py report $(RESULTS)/load.csv --plot $(RESULTS)/load-cdf.png
	for m in delete force scale; do \
		python3 experiments/failover.py report $(RESULTS)/failover-$$m.json --plot $(RESULTS)/failover-$$m.png || exit 1; \
	done

clean:
	rm -rf build dist src/*.egg-info .pytest_cache
	find . -name __pycache__ -prune -exec rm -rf {} +
