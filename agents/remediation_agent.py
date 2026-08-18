"""
Remediation Planner Agent

Given a completed RCA, proposes a structured, typed remediation plan.
The LLM does NOT propose remediation here — this agent uses
the RCA's recommended_actions (which were already cleaned by the RCA agent)
and converts them into a validated RemediationPlan.

The Policy Engine then evaluates the plan before any execution.
"""
from __future__ import annotations

from common.events.schemas import (
    RemediationAction,
    RemediationPlan,
    RiskLevel,
    RootCauseAnalysis,
    new_event_id,
)
from common.logging.logger import get_logger

logger = get_logger(__name__)

# Risk levels per action type
ACTION_RISK_MAP: dict[str, RiskLevel] = {
    "RESTART_POD": RiskLevel.LOW,
    "SCALE_DEPLOYMENT": RiskLevel.LOW,
    "ROLLBACK_DEPLOYMENT": RiskLevel.MEDIUM,
    "CHANGE_CONFIG": RiskLevel.HIGH,
    "DELETE_RESOURCE": RiskLevel.FORBIDDEN,
    "DATABASE_MUTATION": RiskLevel.FORBIDDEN,
}


def plan_remediation(
    incident_id: str,
    rca: RootCauseAnalysis,
    service: str,
    namespace: str,
) -> RemediationPlan | None:
    """
    Converts the RCA's first recommended action into a structured RemediationPlan.
    Returns None if no safe actions are available.
    """
    if not rca.recommended_actions:
        logger.warning("No recommended actions from RCA", incident_id=incident_id)
        return None

    # Take first recommended action
    action_dict = rca.recommended_actions[0]
    action_str = action_dict.get("action", "")

    # Validate it's a known action
    try:
        action = RemediationAction(action_str)
    except ValueError:
        logger.error(
            "Unknown remediation action from RCA",
            action=action_str,
            incident_id=incident_id,
        )
        return None

    risk_level = ACTION_RISK_MAP.get(action.value, RiskLevel.HIGH)

    # Forbidden actions are never planned
    if risk_level == RiskLevel.FORBIDDEN:
        logger.warning(
            "Remediation planner: forbidden action rejected",
            action=action.value,
            incident_id=incident_id,
        )
        return None

    target = action_dict.get("target", service)
    parameters: dict = {}

    if action == RemediationAction.ROLLBACK_DEPLOYMENT:
        parameters["target_revision"] = action_dict.get("target_revision", "previous")

    elif action == RemediationAction.SCALE_DEPLOYMENT:
        parameters["replicas"] = action_dict.get("replicas", 3)

    requires_approval = risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)

    plan = RemediationPlan(
        plan_id=new_event_id(),
        incident_id=incident_id,
        action=action,
        namespace=action_dict.get("namespace", namespace),
        target=target,
        parameters=parameters,
        reason=action_dict.get("reason", rca.root_cause)[:500],
        risk_level=risk_level,
        requires_approval=requires_approval,
        proposed_by="remediation_agent",
    )

    logger.info(
        "Remediation plan proposed",
        incident_id=incident_id,
        action=action.value,
        target=target,
        risk_level=risk_level.value,
        requires_approval=requires_approval,
    )

    return plan
