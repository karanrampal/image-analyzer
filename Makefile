SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.ONESHELL:
.DELETE_ON_ERROR:
MAKEFLAGS += --warn-undefined-variables
MAKEFLAGS += --no-builtin-rules

.DEFAULT_GOAL := help

# Docker
PROJECT := hm-studios-metadata-c54a
LOCATION := europe-west1
REGISTRY := annotate-ar-dev
IMAGE_NAME ?= annotations
VERSION ?= latest
DOCKERFILE ?= Dockerfile
IMG := $(IMAGE_NAME):$(VERSION)

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk -F ':.*##' '{gsub(/^[[:space:]]+/, "", $$2); printf "  %-20s %s\n", $$1, $$2}'

install: ## Install base dependencies
	uv sync --no-editable --no-dev

install-all: ## Install all dependencies
	uv sync --all-groups

test: ## Run unit tests with coverage
	uv run pytest tests/unit_tests -vv --cov=src --benchmark-disable

test-perf: ## Run performance benchmarks
	uv run pytest tests/performance_tests -v --benchmark-columns=min,max,mean,stddev,rounds

test-int: ## Run integration tests (requires network access)
	uv run pytest tests/integration_tests -v --cov=src --benchmark-disable

test-all: ## Run all tests (unit + integration + performance) with coverage, skipping network tests
	uv run pytest -vv --cov=src -m "not network"

format: ## Format code
	uv run ruff format
	uv run ruff check --fix

typecheck: ## Run type checker
	uv run mypy src tests

lint: ## Lint with pylint
	uv run pylint -j 4 src tests

docker-bp: ## Build and push Docker image (override with DOCKERFILE)
	@if [[ -z "$(DOCKERFILE)" ]]; then \
	  echo "Usage: make docker-bp DOCKERFILE=path/to/Dockerfile"; \
	  exit 1; \
	fi
	docker build -f $(DOCKERFILE) -t $(LOCATION)-docker.pkg.dev/$(PROJECT)/$(REGISTRY)/$(IMG) .
	docker push $(LOCATION)-docker.pkg.dev/$(PROJECT)/$(REGISTRY)/$(IMG)

clean: ## Clean caches, coverage, build, and terraform artifacts
	rm -rf dist build
	find . \( -name "__pycache__" -o -name ".mypy_cache" -o -name ".pytest_cache" -o -name ".benchmarks" -o -name ".ruff_cache" -o -name "*.egg-info" -o -name ".ipynb_checkpoints" -o -name ".terraform" -o -name "charts" \) -exec rm -rf {} +
	find . \( -name "*.pyc" -o -name ".coverage" -o -name "coverage.xml" -o -name "*.tfplan" \) -delete

precommit: format lint typecheck test ## Run pre-commit checks (format, lint, typecheck, test)

all: ## Install, lint and test
	$(MAKE) install
	$(MAKE) lint
	$(MAKE) test

.PHONY: help install install-all test test-perf test-integration test-all format typecheck lint docker-bp clean precommit all