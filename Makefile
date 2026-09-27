# ==============================================================================
# INDRA Platform Developer Makefile
# Intelligent National Disaster & Weather Platform
# Smart India Hackathon 2026 - Problem Statement: SIH26069 | Team: Sixth Sense
# ==============================================================================

.DEFAULT_GOAL := help
.PHONY: help dev start bg stop restart status setup infra-up infra-down infra-status doctor test test-integration smoke e2e-backend e2e e2e-reset logs clean

help:
	@./start.sh help

setup:
	@./start.sh setup

dev:
	@./start.sh start

start:
	@./start.sh start

bg:
	@./start.sh bg

stop:
	@./start.sh stop

restart:
	@./start.sh restart

status:
	@./start.sh status

infra-up:
	@./start.sh infra up

infra-down:
	@./start.sh infra down

infra-status:
	@./start.sh infra ps

infra-ps:
	@./start.sh infra ps

doctor:
	@./start.sh doctor

# Backend pytest suites. Both run against the `indra_test` database (see
# backend/tests/conftest.py), never the dev database.
test:
	@cd backend && .venv/bin/pytest -q -m "not integration"

test-integration:
	@cd backend && .venv/bin/pytest -q

# HTTP probes against a running backend (was `make test`).
smoke:
	@./start.sh test

# Playwright against a disposable backend on indra_e2e (port 8100), never the
# dev stack. Run `make e2e-backend` in another terminal first.
e2e-backend:
	@./start.sh e2e-backend

e2e:
	@cd frontend && E2E_API_URL=http://localhost:8100 E2E_EXPECT_DB=indra_e2e npx playwright test

e2e-reset:
	@./start.sh e2e-reset

logs:
	@./start.sh logs

clean:
	@./start.sh clean
# ── Alert Engine ──────────────────────────────────────────────────────────────
alert-engine-demo:
	@echo "Starting Alert Engine in DEMO mode (port 8001)..."
	@pip install -q -r alert_engine/requirements.txt
	ALERT_ENGINE_MODE=demo python -m alert_engine.main

alert-engine-live:
	@echo "Starting Alert Engine in LIVE mode (port 8001)..."
	@pip install -q -r alert_engine/requirements.txt
	ALERT_ENGINE_MODE=live python -m alert_engine.main

alert-engine: alert-engine-demo
