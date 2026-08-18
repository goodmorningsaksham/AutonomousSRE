"""
Integration Tests — AI RCA & Remediation Planning

Tests:
1. Mock LLM structured response generation across failure types
2. Root Cause Analysis prompt building and schema parsing
3. Stripping of forbidden/unsafe actions from LLM output
4. Remediation planner generating typed RemediationPlan with correct risk levels
5. Runbook and historical incident retrieval tool structures
"""
from __future__ import annotations

import json
import pytest

from agents.llm_provider import MockLLMProvider
from agents.remediation_agent import plan_remediation
from agents.root_cause_agent import _build_user_prompt, run_rca
from common.events.schemas import (
    RemediationAction,
    RemediationPlan,
    RiskLevel,
    RootCauseAnalysis,
    new_event_id,
)


@pytest.mark.asyncio
class TestMockLLMProvider:
    async def test_db_exhaustion_scenario_rca(self):
        provider = MockLLMProvider()
        text, tokens, cost = await provider.complete(
            system_prompt="RCA prompt",
            user_prompt="DB connection pool exhaustion detected on payment service with pool utilization at 96%",
        )
        assert tokens > 0
        data = json.loads(text)
        assert "connection" in data["root_cause"].lower()
        assert data["confidence"] >= 0.8
        assert data["suspected_component"] == "payment"
        assert len(data["evidence"]) >= 2
        assert len(data["recommended_actions"]) > 0

    async def test_pod_crash_scenario_rca(self):
        provider = MockLLMProvider()
        text, tokens, cost = await provider.complete(
            system_prompt="RCA prompt",
            user_prompt="Pod payment-xxx crashed with OOMKilled exit status, restart count 5 in 10 minutes",
        )
        data = json.loads(text)
        assert "oomkilled" in data["root_cause"].lower() or "memory" in data["root_cause"].lower()
        assert data["confidence"] >= 0.8
        assert data["recommended_actions"][0]["action"] in ("ROLLBACK_DEPLOYMENT", "RESTART_POD", "SCALE_DEPLOYMENT")

    async def test_latency_scenario_rca(self):
        provider = MockLLMProvider()
        text, tokens, cost = await provider.complete(
            system_prompt="RCA prompt",
            user_prompt="p95 latency spike to 2.5s on payment service slow database queries",
        )
        data = json.loads(text)
        assert "latency" in data["root_cause"].lower() or "slow" in data["root_cause"].lower()
        assert data["confidence"] >= 0.7


class TestPromptBuilding:
    def test_build_user_prompt_aggregates_telemetry(self):
        evidence = {
            "prometheus": {
                "metrics": {
                    "error_rate_5m": [{"value": [1700000000, "0.55"]}],
                    "p95_latency_seconds": [{"value": [1700000000, "2.1"]}],
                }
            },
            "loki": {
                "log_count": 5,
                "logs": [{"timestamp": "2024-01-01T00:00:00Z", "line": "connection pool exhausted"}],
            },
            "kubernetes": {
                "pod_count": 2,
                "pods": [{"name": "payment-123", "phase": "Running", "container_statuses": []}],
                "deployment": {"name": "payment", "replicas": 2, "ready_replicas": 2},
            },
            "deployments": {"recent_deployments": []},
            "history": {"similar_incidents": []},
            "runbooks": {"runbooks": []},
            "dependencies": {"depends_on": ["postgres"], "depended_on_by": ["checkout"]},
        }

        prompt = _build_user_prompt("inc-123", "payment", "production", evidence)
        assert "Incident: inc-123" in prompt
        assert "Service: payment" in prompt
        assert "Metrics (Prometheus)" in prompt
        assert "Logs (Loki)" in prompt
        assert "Kubernetes State" in prompt
        assert "Service Dependencies" in prompt


class TestRemediationPlanning:
    def test_plan_remediation_from_rca(self):
        rca = RootCauseAnalysis(
            root_cause="DB connection exhaustion",
            confidence=0.92,
            suspected_component="payment",
            recommended_actions=[
                {"action": "ROLLBACK_DEPLOYMENT", "target": "payment", "namespace": "production", "reason": "Connection leak in v42"}
            ]
        )
        plan = plan_remediation("inc-999", rca, "payment", "production")
        assert plan is not None
        assert plan.action == RemediationAction.ROLLBACK_DEPLOYMENT
        assert plan.target == "payment"
        assert plan.namespace == "production"
        assert plan.risk_level == RiskLevel.MEDIUM
        assert plan.requires_approval is True

    def test_plan_scale_deployment(self):
        rca = RootCauseAnalysis(
            root_cause="CPU saturation",
            confidence=0.85,
            suspected_component="payment",
            recommended_actions=[
                {"action": "SCALE_DEPLOYMENT", "target": "payment", "namespace": "production", "replicas": 4, "reason": "Scale to relieve CPU load"}
            ]
        )
        plan = plan_remediation("inc-999", rca, "payment", "production")
        assert plan is not None
        assert plan.action == RemediationAction.SCALE_DEPLOYMENT
        assert plan.parameters.get("replicas") == 4
        assert plan.risk_level == RiskLevel.LOW
        assert plan.requires_approval is False
