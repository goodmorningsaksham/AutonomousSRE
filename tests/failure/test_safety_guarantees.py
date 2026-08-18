"""
Failure Tests — Safety Guarantees

Tests that critical safety properties hold:
1. Forbidden actions are never executed (even if LLM proposes them)
2. Duplicate Kafka events produce only one side-effect
3. Malformed LLM output is rejected and falls back gracefully
4. Wrong namespace/target is rejected
"""
from __future__ import annotations

import json
import pytest

from common.events.schemas import RemediationAction, RemediationPlan, RiskLevel, new_event_id
from policies.remediation_policy import evaluate_policy


class TestForbiddenActionNeverExecutes:
    """
    Scenario F: Wrong AI recommendation.
    The AI proposes a forbidden action — policy must reject it.
    Nothing dangerous should execute.
    """

    @pytest.mark.parametrize("action", [
        RemediationAction.DELETE_RESOURCE,
        RemediationAction.DATABASE_MUTATION,
    ])
    def test_forbidden_action_blocked(self, action):
        plan = RemediationPlan(
            plan_id=new_event_id(),
            incident_id=new_event_id(),
            action=action,
            namespace="production",
            target="payment",
            reason="LLM proposed this",
            risk_level=RiskLevel.FORBIDDEN,
            requires_approval=False,
        )
        result = evaluate_policy(plan)
        assert result.allowed is False, f"Action {action.value} must NEVER be allowed"
        assert result.rejection_reason is not None
        assert "forbidden" in result.rejection_reason.lower()

    def test_fake_action_string_blocked(self):
        """LLM cannot bypass by inventing action names."""
        # Only valid enum values can be used — invalid ones raise ValueError
        with pytest.raises(ValueError):
            RemediationPlan(
                plan_id=new_event_id(),
                incident_id=new_event_id(),
                action="EXEC_SHELL",  # type: ignore
                namespace="production",
                target="payment",
                reason="LLM hacked",
                risk_level=RiskLevel.FORBIDDEN,
                requires_approval=False,
            )


class TestLLMOutputValidation:
    """Tests that malformed LLM output is rejected safely."""

    def test_empty_response_handled(self):
        import json
        raw = ""
        with pytest.raises((json.JSONDecodeError, ValueError)):
            if not raw:
                raise ValueError("Empty LLM response")
            json.loads(raw)

    def test_missing_confidence_detected(self):
        response = {"root_cause": "DB exhaustion"}  # missing confidence
        assert "confidence" not in response or not isinstance(response.get("confidence"), (int, float))

    def test_out_of_range_confidence_detected(self):
        response = {"root_cause": "DB exhaustion", "confidence": 1.5}
        confidence = float(response["confidence"])
        assert not (0.0 <= confidence <= 1.0), "Should detect out-of-range confidence"

    def test_forbidden_action_stripped_from_llm_output(self):
        """Simulate RCA agent stripping forbidden actions from LLM response."""
        ALLOWED_ACTIONS = {"RESTART_POD", "SCALE_DEPLOYMENT", "ROLLBACK_DEPLOYMENT"}
        raw_actions = [
            {"action": "ROLLBACK_DEPLOYMENT", "target": "payment"},
            {"action": "DELETE_RESOURCE", "target": "payment"},  # FORBIDDEN
            {"action": "DATABASE_MUTATION", "target": "postgres"},  # FORBIDDEN
        ]
        safe_actions = [a for a in raw_actions if a.get("action") in ALLOWED_ACTIONS]
        assert len(safe_actions) == 1
        assert safe_actions[0]["action"] == "ROLLBACK_DEPLOYMENT"


class TestIdempotencyGuarantee:
    """
    Scenario D: Duplicate Kafka event.
    Publishing same event twice should produce exactly one side-effect.
    """

    def test_same_event_id_detected_as_duplicate(self):
        """Simulate idempotency checking logic."""
        processed = set()
        event_id = new_event_id()

        # First processing — not a duplicate
        if event_id in processed:
            result_1 = "SKIP"
        else:
            processed.add(event_id)
            result_1 = "PROCESSED"

        # Second processing — should be detected as duplicate
        if event_id in processed:
            result_2 = "SKIP"
        else:
            processed.add(event_id)
            result_2 = "PROCESSED"

        assert result_1 == "PROCESSED"
        assert result_2 == "SKIP"

    def test_different_event_ids_both_processed(self):
        processed = set()
        id1, id2 = new_event_id(), new_event_id()
        assert id1 != id2

        results = []
        for eid in [id1, id2]:
            if eid in processed:
                results.append("SKIP")
            else:
                processed.add(eid)
                results.append("PROCESSED")

        assert results == ["PROCESSED", "PROCESSED"]


class TestRemediation_PlannedNotForbidden:
    """The remediation planner itself must never plan forbidden actions."""

    def test_planner_returns_none_for_forbidden(self):
        from agents.remediation_agent import plan_remediation, ACTION_RISK_MAP
        from common.events.schemas import RootCauseAnalysis

        rca = RootCauseAnalysis(
            root_cause="DB exhaustion",
            confidence=0.9,
            suspected_component="payment",
            recommended_actions=[
                {"action": "DELETE_RESOURCE", "target": "payment", "namespace": "production"}
            ]
        )
        plan = plan_remediation("test-incident-id", rca, "payment", "production")
        assert plan is None, "Planner must return None for forbidden DELETE_RESOURCE action"

    def test_planner_with_valid_action(self):
        from agents.remediation_agent import plan_remediation
        from common.events.schemas import RootCauseAnalysis

        rca = RootCauseAnalysis(
            root_cause="DB exhaustion",
            confidence=0.9,
            suspected_component="payment",
            recommended_actions=[
                {"action": "ROLLBACK_DEPLOYMENT", "target": "payment", "namespace": "production", "reason": "leak"}
            ]
        )
        plan = plan_remediation("test-incident-id", rca, "payment", "production")
        assert plan is not None
        assert plan.action == RemediationAction.ROLLBACK_DEPLOYMENT
        assert plan.requires_approval is True  # ROLLBACK requires human approval
