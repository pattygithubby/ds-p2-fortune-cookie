IMAGE ?= fortune-cookie

.PHONY: install test build deploy undeploy clean

install:        ## install the package and dev tools into the current environment
	pip install -e '.[dev]'

test:           ## run all tests
	python3 -m pytest

build:          ## build the container image
	docker build -t $(IMAGE) .

deploy:         ## apply the Kubernetes manifests
	kubectl apply -k deploy/k8s

undeploy:       ## remove everything deploy created
	kubectl delete -k deploy/k8s

clean:
	rm -rf build dist src/*.egg-info .pytest_cache
	find . -name __pycache__ -prune -exec rm -rf {} +
