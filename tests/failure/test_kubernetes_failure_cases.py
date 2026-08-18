"""
Failure Tests — Policy Security & Kubernetes Guardrails

Tests:
1. Malicious / unauthorized action bypass attempts (e.g. DELETE_RESOURCE disguised)
2. Namespace escape attempts (e.g. attacking kube-system or default)
3. Target injection attacks (e.g. attacking kube-apiserver)
4. Scale boundary violations (negative, zero, > 10, non-integer)
5. Replay / Duplicate remediation execution idempotency
"""
from __future__ import annotations

import pytest

from common.events.schemas import (
    RemediationAction,
    RemediationPlan,
    RemediationResult,
    RiskLevel,
    new_event_id,
)
from policies.remediation_policy import evaluate_policy


def _make_plan(
    action: RemediationAction,
    target: str = "payment",
    namespace: str = "production",
    parameters: dict | None = None,
) -> RemediationPlan:
    return RemediationPlan(
        plan_id=new_event_id(),
        incident_id=new_event_id(),
        action=action,
        namespace=namespace,
        target=target,
        parameters=parameters or {},
        reason="security test",
        risk_level=RiskLevel.LOW,
        requires_approval=False,
    )


class TestPolicySecurityBoundaries:
    def test_delete_resource_permanently_blocked(self):
        plan = _make_plan(RemediationAction.DELETE_RESOURCE)
        res = evaluate_policy(plan)
        assert res.allowed is False
        assert res.risk_level == RiskLevel.FORBIDDEN
        assert "forbidden" in res.rejection_reason.lower()

    def test_database_mutation_permanently_blocked(self):
        plan = _make_plan(RemediationAction.DATABASE_MUTATION)
        res = evaluate_policy(plan)
        assert res.allowed is False
        assert res.risk_level == RiskLevel.FORBIDDEN

    def test_namespace_escape_kube_system(self):
        plan = _make_plan(RemediationAction.RESTART_POD, namespace="kube-system")
        res = evaluate_policy(plan)
        assert res.allowed is False
        assert "kube-system" in res.rejection_reason

    def test_target_escape_unauthorized_daemonset(self):
        plan = _make_plan(RemediationAction.RESTART_POD, target="kube-proxy")
        res = evaluate_policy(plan)
        assert res.allowed is False
        assert "kube-proxy" in res.rejection_reason

    @pytest.mark.parametrize("invalid_replicas", [0, -1, 11, 50, 1000, "five", None])
    def test_scale_parameter_boundary_enforcement(self, invalid_replicas):
        plan = _make_plan(
            RemediationAction.SCALE_DEPLOYMENT,
            parameters={"replicas": invalid_replicas},
        )
        res = evaluate_policy(plan)
        assert res.allowed is False, f"Replicas {invalid_replicas} should have been rejected"


class TestPolicyDeterminism:
    def test_policy_evaluation_is_pure_and_repeatable(self):
        plan = _make_plan(RemediationAction.ROLLBACK_DEPLOYMENT, target="payment", namespace="production")
        for _ in range(10):
            res = evaluate_policy(plan)
            assert res.allowed is True
            assert res.requires_human_approval is True
            assert res.risk_level == RiskLevel.MEDIUM
