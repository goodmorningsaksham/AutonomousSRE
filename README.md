# Aegis — Autonomous SRE & Incident Response Platform

> **Event-driven, Kubernetes-native incident response with AI-assisted root cause analysis and deterministic policy-controlled remediation.**

Aegis detects production failures, correlates alerts, investigates incidents using telemetry-aware AI, proposes safe remediation, executes approved actions, and verifies recovery — automatically and durably.

---

## Architecture

```
Alertmanager → Ingestor (FastAPI) → Kafka (alerts.raw)
                                         │
                                   Correlator Worker
                                   (service dependency graph + fingerprinting)
                                         │ Postgres (incidents, outbox)
                                   Outbox Publisher → Kafka (incidents.created)
                                         │
                                   Investigator Worker
                                         │ Temporal Workflow (durable)
                                         ├─ Evidence Collection (Prometheus, Loki, Tempo, K8s)
                                         ├─ LLM Root Cause Analysis (OpenAI / Mock)
                                         ├─ Remediation Planner
                                         ├─ Policy Engine (deterministic, no LLM)
                                         ├─ [Human Approval Gate if required]
                                         ├─ Kubernetes Executor (restart/scale/rollback)
                                         └─ Verification (post-remediation health check)
                                                     │
                                              Incident RESOLVED
```

### Safety Architecture

The AI is treated as an **untrusted probabilistic component**:

| Layer | What it does |
|-------|-------------|
| **Tools** | Validate args, apply timeouts, sanitize output before LLM sees it |
| **RCA Agent** | Validates LLM JSON schema; strips forbidden actions before returning |
| **Remediation Planner** | Maps actions to risk levels; blocks FORBIDDEN actions |
| **Policy Engine** | Deterministic; validates namespace, target, parameter bounds |
| **K8s Executor** | Idempotent; simulates when K8s unavailable |
| **Temporal** | Durable; survives crashes; approval signals required for MEDIUM+ risk |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API / Ingestor | Python 3.12 + FastAPI + uvicorn |
| Event Backbone | Apache Kafka (aiokafka) |
| State Store | PostgreSQL 16 + pgvector + SQLAlchemy 2 (async) |
| Migrations | Alembic |
| Workflow Engine | Temporal |
| AI / LLM | OpenAI gpt-4o (or mock for local dev) |
| Kubernetes Client | kubernetes-python |
| Metrics | Prometheus + Grafana |
| Logs | Loki + Promtail + structlog |
| Traces | Tempo + OpenTelemetry Collector |
| Frontend | React 18 + Vite + TypeScript |

---

## Quick Start

### Prerequisites
- Docker Desktop
- Python 3.12+
- Node.js 20+

### 1. Clone and Install

```bash
git clone https://github.com/goodmorningsaksham/AutonomousSRE
cd ai-sre
pip install -r requirements.txt
cp .env.example .env
```

### 2. Start Infrastructure

```bash
make infra-up
```

This starts: PostgreSQL, Kafka, Redis, Temporal, Prometheus, Alertmanager, Loki, Tempo, Grafana, OpenTelemetry Collector.

Wait ~15 seconds, then:

```bash
make db-migrate
make seed
make kafka-init
```

### 3. Start Demo Services

```bash
make demo-up
```

Starts: checkout (`:3001`), payment (`:3002`), inventory (`:3003`).

### 4. Start Aegis

```bash
# In separate terminals (or run all in background):
make dev-ingestor       # Alert Ingestor  :8001
make dev-correlator     # Correlator Worker
make dev-outbox         # Outbox Publisher
make dev-investigator   # Investigator Worker
make dev-api            # REST API :8000
```

### 5. Start Frontend

```bash
make frontend-dev       # http://localhost:5173
```

---

## Demo: Incident Lifecycle

### Option A: Manual Alert Injection

```bash
curl -X POST http://localhost:8001/api/v1/alerts \
  -H 'Content-Type: application/json' \
  -d '{
    "alert_name": "HighErrorRate",
    "service": "payment",
    "namespace": "production",
    "severity": "critical",
    "status": "firing",
    "labels": {"service": "payment"},
    "annotations": {"summary": "Error rate above 50%"}
  }'
```

### Option B: Real Failure Injection

```bash
# Start traffic
make traffic                     # 5 RPS of checkout requests

# Inject DB pool exhaustion
make inject-db-exhaustion        # payment service loses all DB connections
#  → Alertmanager fires HighErrorRate alert
#  → Ingestor publishes to Kafka
#  → Correlator creates incident
#  → Investigator runs RCA (confidence ~91%)
#  → Policy: ROLLBACK_DEPLOYMENT requires approval
#  → Approve in UI: http://localhost:5173/approvals
#  → K8s executor rolls back
#  → Verification confirms recovery
#  → Incident resolved

# Recover
make recover
```

### Approval Flow (ROLLBACK requires human sign-off)

```bash
# Get pending approvals
curl http://localhost:8000/api/v1/approvals/pending

# Approve
curl -X POST http://localhost:8000/api/v1/approvals/{approval_id}/approve \
  -H 'Content-Type: application/json' \
  -d '{"decision": "approved", "approved_by": "alice", "notes": "confirmed deployment was bad"}'
```

---

## Testing

```bash
make test              # unit + failure tests (no infra needed)
make test-e2e          # end-to-end (requires full stack running)
```

### Unit Tests
- Policy engine: all actions, namespaces, targets, parameter bounds
- Event schemas: UUID uniqueness, Kafka topic completeness, fingerprinting
- LLM output validation: forbidden action stripping, malformed response handling
- Idempotency: duplicate event handling
- Remediation planner: forbidden action blocking

---

## Benchmark

```bash
make benchmark         # 100 scenarios: MTTD, MTTR, RCA accuracy
make benchmark-quick   # 10 scenarios for CI
```

Metrics per scenario:
- `mttd_seconds` — failure injection → alert created
- `mttr_seconds` — alert → incident RESOLVED
- `root_cause_correct` — AI root cause vs expected
- `remediation_success` — incident resolved
- `unsafe_actions` — forbidden actions attempted (must be 0)
- `duplicate_side_effects` — same action executed twice (must be 0)

---

## Observability

| Dashboard | URL |
|-----------|-----|
| Grafana | http://localhost:3000 (admin/admin) |
| Prometheus | http://localhost:9090 |
| Temporal UI | http://localhost:8088 |
| Alertmanager | http://localhost:9093 |
| Aegis API docs | http://localhost:8000/docs |
| Aegis UI | http://localhost:5173 |

---

## Configuration

Copy `.env.example` to `.env` and edit:

```bash
# LLM (defaults to mock — works offline)
LLM_PROVIDER=mock              # or: openai
OPENAI_API_KEY=sk-...

# Kubernetes (defaults to kubeconfig)
KUBERNETES_IN_CLUSTER=false    # set true inside cluster

# Safety
AEGIS_K8S_ALLOWED_NAMESPACES=production,staging,demo
AEGIS_K8S_ALLOWED_DEPLOYMENTS=checkout,payment,inventory
```

---

## Project Structure

```
ai-sre/
├── common/
│   ├── config/settings.py          # Pydantic settings
│   ├── events/schemas.py           # All Kafka event schemas
│   ├── kafka/{producer,consumer,admin}.py
│   └── logging/logger.py
├── database/
│   ├── models/models.py            # SQLAlchemy ORM
│   ├── migrations/                 # Alembic
│   └── session.py
├── agents/
│   ├── tools.py                    # Investigation tools (Prometheus, Loki, K8s, RAG)
│   ├── root_cause_agent.py         # RCA orchestrator
│   ├── remediation_agent.py        # Remediation planner
│   └── llm_provider.py             # LLM abstraction (OpenAI / Mock)
├── policies/
│   └── remediation_policy.py       # Deterministic policy engine
├── services/
│   ├── alert_ingestor/main.py      # FastAPI webhook receiver
│   ├── correlator/main.py          # Alert grouping worker
│   ├── investigator/main.py        # Workflow trigger
│   ├── outbox_publisher/main.py    # Transactional outbox
│   ├── api/main.py                 # REST API + approvals
│   ├── remediation/k8s_executor.py # Kubernetes actions
│   └── demo/{checkout,payment,inventory}/ # Demo production services
├── workflows/
│   └── incident_workflow.py        # Temporal durable workflow
├── infrastructure/
│   ├── prometheus/                 # Prometheus + alert rules
│   ├── alertmanager/
│   ├── grafana/
│   ├── loki/
│   ├── tempo/
│   └── otel/
├── scripts/
│   ├── failure_injection/injector.py
│   ├── traffic_generator.py
│   ├── benchmark/benchmark_runner.py
│   └── seed/seed_data.py
├── tests/
│   ├── unit/                       # Policy, schemas, correlator
│   ├── failure/                    # Safety guarantees
│   └── e2e/                        # Full lifecycle
├── frontend/                       # React + Vite + TypeScript
├── docker-compose.yml
├── Makefile
└── requirements.txt
```

---

## Design Decisions

**Why Temporal?** Crash-resilient durable execution. If the worker dies mid-investigation, Temporal replays from the last committed activity. The approval signal mechanism is built-in.

**Why transactional outbox?** Ensures Kafka events are never lost even if the broker is temporarily unavailable. Business state and event publication commit atomically.

**Why a deterministic policy engine?** The LLM cannot bypass safety constraints. The policy layer is pure Python with no AI calls — it validates namespace, target, action type, and parameter bounds deterministically.

**Why mock LLM?** Aegis works fully offline without OpenAI costs. Set `LLM_PROVIDER=mock` to use the keyword-based mock that generates realistic structured RCA for testing.
