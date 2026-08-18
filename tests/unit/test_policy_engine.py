"""
Unit Tests — Policy Engine

Tests that the deterministic policy engine correctly:
- Allows safe actions automatically
- Requires approval for medium-risk actions
- Rejects forbidden actions
- Validates namespaces and targets
- Validates parameter bounds
"""
from __future__ import annotations

import pytest

from common.events.schemas import RemediationAction, RemediationPlan, RiskLevel, new_event_id
from policies.remediation_policy import PolicyEvaluationResult, evaluate_policy


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
        reason="test",
        risk_level=RiskLevel.LOW,
        requires_approval=False,
    )


class TestPolicyEngineAllowedActions:
    def test_restart_pod_auto_approved(self):
        plan = _make_plan(RemediationAction.RESTART_POD)
        result = evaluate_policy(plan)
        assert result.allowed is True
        assert result.requires_human_approval is False
        assert result.auto_approved is True
        assert result.risk_level == RiskLevel.LOW

    def test_scale_deployment_auto_approved(self):
        plan = _make_plan(RemediationAction.SCALE_DEPLOYMENT, parameters={"replicas": 3})
        result = evaluate_policy(plan)
        assert result.allowed is True
        assert result.requires_human_approval is False
        assert result.auto_approved is True

    def test_rollback_requires_approval(self):
        plan = _make_plan(RemediationAction.ROLLBACK_DEPLOYMENT)
        result = evaluate_policy(plan)
        assert result.allowed is True
        assert result.requires_human_approval is True
        assert result.auto_approved is False
        assert result.risk_level == RiskLevel.MEDIUM


class TestPolicyEngineForbiddenActions:
    def test_delete_resource_forbidden(self):
        plan = _make_plan(RemediationAction.DELETE_RESOURCE)
        result = evaluate_policy(plan)
        assert result.allowed is False
        assert result.risk_level == RiskLevel.FORBIDDEN
        assert result.rejection_reason is not None

    def test_database_mutation_forbidden(self):
        plan = _make_plan(RemediationAction.DATABASE_MUTATION)
        result = evaluate_policy(plan)
        assert result.allowed is False
        assert result.risk_level == RiskLevel.FORBIDDEN


class TestPolicyEngineNamespaceValidation:
    def test_disallowed_namespace_rejected(self):
        plan = _make_plan(RemediationAction.RESTART_POD, namespace="kube-system")
        result = evaluate_policy(plan)
        assert result.allowed is False
        assert "kube-system" in (result.rejection_reason or "")

    def test_allowed_namespace_passes(self):
        for ns in ["production", "staging", "demo"]:
            plan = _make_plan(RemediationAction.RESTART_POD, namespace=ns)
            result = evaluate_policy(plan)
            assert result.allowed is True, f"Expected {ns} to be allowed"


class TestPolicyEngineTargetValidation:
    def test_disallowed_target_rejected(self):
        plan = _make_plan(RemediationAction.RESTART_POD, target="kube-dns")
        result = evaluate_policy(plan)
        assert result.allowed is False
        assert "kube-dns" in (result.rejection_reason or "")

    def test_allowed_targets_pass(self):
        for target in ["checkout", "payment", "inventory"]:
            plan = _make_plan(RemediationAction.RESTART_POD, target=target)
            result = evaluate_policy(plan)
            assert result.allowed is True, f"Expected {target} to be allowed"


class TestPolicyEngineScaleBounds:
    def test_scale_exceeds_max_rejected(self):
        plan = _make_plan(
            RemediationAction.SCALE_DEPLOYMENT,
            parameters={"replicas": 100}
        )
        result = evaluate_policy(plan)
        assert result.allowed is False
        assert "100" in (result.rejection_reason or "")

    def test_scale_below_min_rejected(self):
        plan = _make_plan(
            RemediationAction.SCALE_DEPLOYMENT,
            parameters={"replicas": 0}
        )
        result = evaluate_policy(plan)
        assert result.allowed is False

    def test_scale_within_bounds_allowed(self):
        plan = _make_plan(
            RemediationAction.SCALE_DEPLOYMENT,
            parameters={"replicas": 5}
        )
        result = evaluate_policy(plan)
        assert result.allowed is True

    def test_scale_non_integer_replicas_rejected(self):
        plan = _make_plan(
            RemediationAction.SCALE_DEPLOYMENT,
            parameters={"replicas": "many"}
        )
        result = evaluate_policy(plan)
        assert result.allowed is False
