# ═══════════════════════════════════════════════════════════════════════════════
# Aegis — Autonomous SRE Platform Makefile
# ═══════════════════════════════════════════════════════════════════════════════

.DEFAULT_GOAL := help
SHELL := /bin/bash
PYTHONPATH := $(shell pwd)
export PYTHONPATH

.PHONY: help setup infra-up infra-down db-migrate kafka-init seed \
        dev-ingestor dev-correlator dev-investigator dev-api dev-all \
        demo-up demo-down traffic \
        test test-unit test-failure test-integration test-e2e \
        benchmark inject-db-exhaustion inject-latency inject-bad-deployment recover \
        frontend-install frontend-dev frontend-build \
        commit git-phases clean logs

# ─── Colors ──────────────────────────────────────────────────────────────────
GREEN  := \033[0;32m
YELLOW := \033[0;33m
RED    := \033[0;31m
CYAN   := \033[0;36m
RESET  := \033[0m

help: ## Show this help
	@echo ""
	@echo "  $(CYAN)Aegis — Autonomous SRE Platform$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-30s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ─── Setup ───────────────────────────────────────────────────────────────────
setup: ## Install all Python dependencies
	@echo "$(CYAN)Installing Python dependencies...$(RESET)"
	pip install -r requirements.txt
	@echo "$(CYAN)Installing frontend dependencies...$(RESET)"
	cd frontend && npm install
	@echo "$(GREEN)✓ Setup complete$(RESET)"

copy-env: ## Copy .env.example to .env
	@if [ ! -f .env ]; then cp .env.example .env; echo "$(GREEN)✓ .env created$(RESET)"; else echo "$(YELLOW).env already exists$(RESET)"; fi

# ─── Infrastructure ───────────────────────────────────────────────────────────
infra-up: ## Start all infrastructure (Postgres, Kafka, Redis, Temporal, Observability)
	@echo "$(CYAN)Starting infrastructure...$(RESET)"
	docker compose up -d postgres demo-postgres redis demo-redis kafka temporal temporal-ui \
		prometheus alertmanager loki tempo grafana otel-collector promtail
	@echo "$(CYAN)Waiting for services to be healthy...$(RESET)"
	@sleep 10
	@echo "$(GREEN)✓ Infrastructure started$(RESET)"
	@echo ""
	@echo "  Grafana:      http://localhost:3000  (admin/admin)"
	@echo "  Prometheus:   http://localhost:9090"
	@echo "  Temporal UI:  http://localhost:8088"
	@echo "  Alertmanager: http://localhost:9093"

infra-down: ## Stop all infrastructure
	docker compose down

infra-logs: ## Follow infrastructure logs
	docker compose logs -f kafka postgres temporal

# ─── Database ─────────────────────────────────────────────────────────────────
db-migrate: ## Run Alembic migrations
	@echo "$(CYAN)Running database migrations...$(RESET)"
	alembic upgrade head
	@echo "$(GREEN)✓ Migrations applied$(RESET)"

db-reset: ## Drop and recreate database (DESTRUCTIVE)
	@echo "$(RED)Resetting database...$(RESET)"
	alembic downgrade base
	alembic upgrade head

seed: ## Seed runbooks and historical incidents
	@echo "$(CYAN)Seeding database...$(RESET)"
	python scripts/seed/seed_data.py
	@echo "$(GREEN)✓ Seed complete$(RESET)"

# ─── Kafka ────────────────────────────────────────────────────────────────────
kafka-init: ## Create all required Kafka topics
	@echo "$(CYAN)Initializing Kafka topics...$(RESET)"
	python -c "import asyncio; from common.kafka.admin import ensure_topics_exist; asyncio.run(ensure_topics_exist())"
	@echo "$(GREEN)✓ Kafka topics created$(RESET)"

# ─── Aegis Services (local dev) ───────────────────────────────────────────────
dev-ingestor: ## Start alert ingestor locally
	python -m services.alert_ingestor.main

dev-correlator: ## Start correlator worker locally
	python -m services.correlator.main

dev-investigator: ## Start investigator worker locally
	python -m services.investigator.main

dev-outbox: ## Start outbox publisher locally
	python -m services.outbox_publisher.main

dev-api: ## Start main API locally
	python -m services.api.main

dev-temporal-worker: ## Start Temporal workflow worker locally
	python -m workflows.incident_workflow

# ─── Demo Services ────────────────────────────────────────────────────────────
demo-up: ## Start demo production services
	docker compose up -d checkout-service payment-service inventory-service
	@echo "$(GREEN)✓ Demo services started$(RESET)"
	@echo ""
	@echo "  Checkout:   http://localhost:3001"
	@echo "  Payment:    http://localhost:3002"
	@echo "  Inventory:  http://localhost:3003"

demo-down: ## Stop demo services
	docker compose stop checkout-service payment-service inventory-service

traffic: ## Start traffic generator (5 RPS, infinite)
	python scripts/traffic_generator.py --rps 5

# ─── Aegis Deploy (Docker) ────────────────────────────────────────────────────
aegis-up: ## Start all Aegis services via Docker Compose
	docker compose up -d aegis-api aegis-ingestor aegis-correlator aegis-investigator \
		aegis-outbox-publisher aegis-temporal-worker

aegis-down: ## Stop Aegis services
	docker compose stop aegis-api aegis-ingestor aegis-correlator aegis-investigator \
		aegis-outbox-publisher aegis-temporal-worker

# ─── Full Stack ───────────────────────────────────────────────────────────────
up: infra-up demo-up aegis-up ## Start everything
	@echo ""
	@echo "$(GREEN)✓ Aegis is running!$(RESET)"
	@echo ""
	@echo "  Aegis API:    http://localhost:8000/docs"
	@echo "  Aegis UI:     http://localhost:5173"
	@echo "  Ingestor:     http://localhost:8001"
	@echo "  Grafana:      http://localhost:3000"
	@echo "  Temporal UI:  http://localhost:8088"

down: ## Stop all services
	docker compose down

# ─── Testing ──────────────────────────────────────────────────────────────────
test: test-unit test-failure ## Run unit + failure tests

test-unit: ## Run unit tests
	@echo "$(CYAN)Running unit tests...$(RESET)"
	pytest tests/unit/ -v

test-failure: ## Run failure/safety tests
	@echo "$(CYAN)Running failure tests...$(RESET)"
	pytest tests/failure/ -v

test-integration: ## Run integration tests (requires running infrastructure)
	@echo "$(CYAN)Running integration tests...$(RESET)"
	pytest tests/integration/ -v

test-e2e: ## Run end-to-end tests (requires full stack running)
	@echo "$(CYAN)Running e2e tests...$(RESET)"
	pytest tests/e2e/ -v --timeout=120

test-all: ## Run all tests
	pytest tests/ -v

# ─── Failure Injection ────────────────────────────────────────────────────────
inject-db-exhaustion: ## Inject database connection pool exhaustion
	python scripts/failure_injection/injector.py --scenario db-exhaustion

inject-latency: ## Inject artificial latency (2s)
	python scripts/failure_injection/injector.py --scenario latency --latency-ms 2000

inject-bad-deployment: ## Inject bad deployment (80% error rate)
	python scripts/failure_injection/injector.py --scenario bad-deployment --error-rate 0.8

recover: ## Recover all services from failure injection
	python scripts/failure_injection/injector.py --scenario recover

# ─── Benchmark ────────────────────────────────────────────────────────────────
benchmark: ## Run full 100-scenario benchmark suite
	@echo "$(CYAN)Running benchmark (100 scenarios)...$(RESET)"
	python scripts/benchmark/benchmark_runner.py --scenarios 100 --output benchmark_results.json
	@echo "$(GREEN)✓ Benchmark complete. Results in benchmark_results.json$(RESET)"

benchmark-quick: ## Run 10-scenario quick benchmark
	python scripts/benchmark/benchmark_runner.py --scenarios 10 --quick --output benchmark_quick.json

# ─── Frontend ─────────────────────────────────────────────────────────────────
frontend-install: ## Install frontend dependencies
	cd frontend && npm install

frontend-dev: ## Start frontend dev server
	cd frontend && npm run dev

frontend-build: ## Build frontend for production
	cd frontend && npm run build

# ─── Git Commits ─────────────────────────────────────────────────────────────
commit-phases-1-3: ## Commit Phases 1-3 (Structure, DB, Kafka)
	git config user.name "goodmorningsaksham"
	git config user.email "saksham@example.com"
	git add -A
	git commit -m "feat: Phases 1-3 — repo structure, PostgreSQL schema, Kafka backbone

- Common event schemas with Pydantic (all 12 topics)
- SQLAlchemy ORM models with pgvector support
- Alembic initial migration
- aiokafka producer/consumer with at-least-once semantics
- Transactional outbox pattern
- Idempotency tracking via processed_events table
- Structured logging with structlog"

commit-phases-4-6: ## Commit Phases 4-6 (Demo services, Observability, Ingestion)
	git config user.name "goodmorningsaksham"
	git config user.email "saksham@example.com"
	git add -A
	git commit -m "feat: Phases 4-6 — demo services, observability stack, alert ingestion

- Demo checkout/payment/inventory services with Prometheus + OTel
- Failure injection endpoints (db-exhaustion, latency, error-rate)
- Prometheus alert rules (HighErrorRate, HighLatency, DBExhaustion, etc.)
- Alertmanager webhook to Aegis ingestor
- Loki/Tempo/Grafana configuration
- Alert ingestor FastAPI service (publishes to Kafka < 5ms)"

commit-phases-7-9: ## Commit Phases 7-9 (Correlator, State, Investigation tools)
	git config user.name "goodmorningsaksham"
	git config user.email "saksham@example.com"
	git add -A
	git commit -m "feat: Phases 7-9 — correlator, incident state, investigation tools

- Alert correlator with service dependency graph + time windowing
- Incident state machine (DETECTED→RESOLVED)
- All investigation tools (Prometheus, Loki, Tempo, K8s, RAG)
- Tool safety: validation, timeouts, data sanitization"

commit-phases-10-12: ## Commit Phases 10-12 (AI, Remediation, Policy)
	git config user.name "goodmorningsaksham"
	git config user.email "saksham@example.com"
	git add -A
	git commit -m "feat: Phases 10-12 — AI RCA, remediation planner, deterministic policy engine

- Root Cause Analysis agent with OpenAI + Mock LLM providers
- Structured JSON output validation (rejects malformed LLM responses)
- Remediation planner converting RCA → typed RemediationPlan
- Deterministic policy engine (LLM proposes, Policy decides)
- Prometheus counters for policy rejections and unsafe actions"

commit-phases-13-15: ## Commit Phases 13-15 (K8s executor, Temporal, Approvals)
	git config user.name "goodmorningsaksham"
	git config user.email "saksham@example.com"
	git add -A
	git commit -m "feat: Phases 13-15 — K8s executor, Temporal workflow, approval system

- Kubernetes executor with typed actions (restart/scale/rollback)
- Idempotent execution with processed-event deduplication
- Durable Temporal IncidentWorkflow (8 crash-resilient steps)
- Approval signal mechanism (human approve/reject via API)
- Human approval REST API endpoints"

commit-phases-16-18: ## Commit Phases 16-18 (Verification, Failure injection, Benchmark)
	git config user.name "goodmorningsaksham"
	git config user.email "saksham@example.com"
	git add -A
	git commit -m "feat: Phases 16-18 — verification, failure injection, benchmark suite

- Post-remediation verification (Prometheus health checks)
- Failure injection framework (db-exhaustion, latency, bad-deploy, recover)
- 100-scenario automated benchmark measuring MTTD/MTTR/accuracy
- Seed script for runbooks and historical incidents"

commit-phases-19-20: ## Commit Phases 19-20 (Frontend, Tests, README)
	git config user.name "goodmorningsaksham"
	git config user.email "saksham@example.com"
	git add -A
	git commit -m "feat: Phases 19-20 — React dashboard, tests, README

- React+Vite+TypeScript incident console
- Unit tests (policy engine, event schemas, correlation)
- Failure/safety tests (forbidden action blocking, idempotency)
- E2E test (full incident lifecycle)
- Makefile with all developer commands
- README with architecture, setup, and demo instructions"

# ─── Utilities ────────────────────────────────────────────────────────────────
logs: ## Tail all Aegis service logs
	docker compose logs -f aegis-api aegis-ingestor aegis-correlator aegis-investigator

clean: ## Remove Python cache files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage
