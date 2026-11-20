IMAGE ?= fortune-cookie
CLUSTER ?= fortune

.PHONY: install test build cluster load deploy redeploy status undeploy cluster-delete clean

install:        ## install the package and dev tools into the current environment
	pip install -e '.[dev]'

test:           ## run all tests
	python3 -m pytest

build:          ## build the container image
	docker build -t $(IMAGE) .

cluster:        ## create the local kind cluster (site at http://localhost:30080)
	kind create cluster --config deploy/kind-cluster.yaml

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

clean:
	rm -rf build dist src/*.egg-info .pytest_cache
	find . -name __pycache__ -prune -exec rm -rf {} +
