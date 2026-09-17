# way-to-ai — a 0-to-hero roadmap for governed agent tooling.
# `make help` lists every target.

SHELL   := /bin/bash
PY      ?= .venv/bin/python
PIP     ?= .venv/bin/pip
GO_IMG  := golang:1.25-alpine
PROXY_LABS := 4 5 6

.DEFAULT_GOAL := help

# Use a local Go toolchain when one exists, otherwise build in Docker. The labs
# need a binary native to *this host* because the proxy is spawned as a stdio
# child process, and a container cannot be one — so we build in Docker and run
# on the host, rather than running the proxy itself in a container.
HAVE_GO := $(shell command -v go 2>/dev/null)

# The Docker builder is always linux, so left alone it emits an ELF binary that
# the host kernel refuses to exec on macOS ("exec format error"). Detect the
# host's own GOOS/GOARCH and cross-compile to it. The proxies are stdlib-only
# with cgo off, so this is a plain static cross-build with no toolchain to
# install. On linux/amd64 these expand to the builder's own values — a no-op.
HOST_GOOS   := $(shell uname -s | tr '[:upper:]' '[:lower:]')
HOST_GOARCH := $(shell uname -m | sed -e 's/^x86_64$$/amd64/' -e 's/^aarch64$$/arm64/')
GO_DOCKER    = docker run --rm --user "$$(id -u):$$(id -g)" \
	          -v "$$PWD":/src -e HOME=/tmp -e GOCACHE=/tmp/gocache \
	          -e CGO_ENABLED=0 -e GOOS=$(HOST_GOOS) -e GOARCH=$(HOST_GOARCH)

## help: list available targets
help:
	@echo ""
	@echo "  governed MCP, lab by lab"
	@echo ""
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/^## //' | awk -F': ' '{printf "  make %-10s %s\n", $$1, $$2}'
	@echo ""

## setup: create the virtualenv and install Python dependencies
setup:
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt
	@echo "Done. Now: cp secrets.example.sh secrets.sh && \$$EDITOR secrets.sh"

## up: start the control plane (OPA on :8181, Redis on :6379)
up:
	docker compose up -d
	@for i in $$(seq 1 30); do curl -sf localhost:8181/health >/dev/null && break || sleep 1; done
	@curl -sf localhost:8181/health >/dev/null && echo "OPA   ready on :8181" || echo "OPA   NOT ready"
	@docker exec gmcp-redis redis-cli ping >/dev/null 2>&1 && echo "Redis ready on :6379" || echo "Redis NOT ready"

## down: stop the control plane
down:
	docker compose down

## proxies: build the Go enforcement proxies for labs 4, 5 and 6
proxies:
	@mkdir -p bin
	@for n in $(PROXY_LABS); do \
	  echo "building bin/proxy-lab$$n"; \
	  if [ -n "$(HAVE_GO)" ]; then \
	    ( cd lab$$n && go build -o ../bin/proxy-lab$$n ./... ) || exit 1; \
	  else \
	    $(GO_DOCKER) -w /src/lab$$n $(GO_IMG) \
	      go build -o /src/bin/proxy-lab$$n ./... || exit 1; \
	  fi; \
	done
	@ls -1 bin/

## vet: run go vet across every proxy and the gateway
vet:
	@for n in $(PROXY_LABS) ; do \
	  echo "vet lab$$n"; \
	  if [ -n "$(HAVE_GO)" ]; then ( cd lab$$n && go vet ./... ) || exit 1; \
	  else $(GO_DOCKER) -w /src/lab$$n $(GO_IMG) go vet ./... || exit 1; fi; \
	done
	@echo "vet pep"
	@if [ -n "$(HAVE_GO)" ]; then ( cd pep && go vet ./... ); \
	else $(GO_DOCKER) -w /src/pep $(GO_IMG) go vet ./...; fi

## validate: check every gMCP registry against the specification
validate:
	@$(PY) spec/validate.py lab*/policy/tools.gmcp.json lab9/registry/*.json lab9/candidates/*.json

## lab1: Tool Calling — the ungoverned baseline
lab1: ; @$(PY) lab1/app.py
## lab2: ReAct Loop — the runaway-loop problem
lab2: ; @$(PY) lab2/app.py
## lab3: Vanilla MCP — dynamic discovery, delegated execution
lab3: ; @$(PY) lab3/app.py
## lab4: The Proxy — a transparent PEP on the stdio transport
lab4: proxies ; @$(PY) lab4/app.py
## lab5: Identity & OPA — three identities, three outcomes
lab5: proxies ; @$(PY) lab5/app.py
## lab6: Budgets — authorised calls stopped by a spend ceiling
lab6: proxies ; @$(PY) lab6/app.py
## lab7: Red Teaming — attack the layer you just built
lab7: proxies ; @$(PY) lab7/app.py
## lab8: Automated Evals — 50 cases, scored, attested
lab8: proxies ; @$(PY) lab8/app.py
## lab9: The Promotion Gate — reject pr-101, promote pr-102
lab9:
	@-$(PY) lab9/promote.py lab9/candidates/pr-101-add-run-sql.gmcp.json
	@echo ""
	@$(PY) lab9/promote.py lab9/candidates/pr-102-narrow-tools.gmcp.json

## pep: build the deployable Streamable HTTP gateway (bin/gmcp-pep)
pep:
	@mkdir -p bin
	@if [ -n "$(HAVE_GO)" ]; then ( cd pep && go build -o ../bin/gmcp-pep ./... ); \
	else $(GO_DOCKER) -w /src/pep $(GO_IMG) go build -o /src/bin/gmcp-pep ./...; fi
	@echo "built bin/gmcp-pep"

## pep-demo: run upstream + gateway + three identities, then tear down
pep-demo: pep
	@bash scripts/pep-demo.sh

## reset: delete lab databases and clear the Redis ledger
reset:
	@rm -f lab*/test.db lab*/attack.db lab*/eval.db pep/upstream.db
	@docker exec gmcp-redis sh -c "redis-cli --scan --pattern 'gmcp:*' | xargs -r redis-cli del" >/dev/null 2>&1 || true
	@echo "databases removed, ledger cleared"

## clean: reset, plus remove built binaries and reports
clean: reset
	@rm -rf bin lab8/reports/*.json lab8/reports/*.md
	@echo "binaries and reports removed"

.PHONY: help setup up down proxies pep pep-demo vet validate reset clean lab1 lab2 lab3 lab4 lab5 lab6 lab7 lab8 lab9
