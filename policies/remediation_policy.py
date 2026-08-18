"""
Deterministic Policy Engine

This is one of the most critical components of Aegis.

The LLM proposes. The Policy Engine decides.

The Policy Engine is entirely deterministic and never calls the LLM.
It evaluates:
  - Action type and associated risk level
  - Target namespace authorization
  - Target deployment authorization
  - Parameter bounds checking
  - Approval requirements

Policy table:
  RESTART_POD       → LOW       → automatic
  SCALE_DEPLOYMENT  → LOW       → automatic (within limits)
  ROLLBACK_DEPLOYMENT → MEDIUM  → human approval required
  CHANGE_CONFIG     → HIGH      → human approval required
  DELETE_RESOURCE   → FORBIDDEN → never allowed
  DATABASE_MUTATION → FORBIDDEN → never allowed

The LLM can NEVER bypass this layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from common.config.settings import get_settings
from common.events.schemas import RemediationAction, RemediationPlan, RiskLevel
from common.logging.logger import get_logger
from prometheus_client import Counter

logger = get_logger(__name__)
settings = get_settings()

# ── Prometheus Metrics ────────────────────────────────────────────────────────
POLICY_REJECTIONS = Counter(
    "aegis_policy_rejections_total",
    "Total remediation plans rejected by policy engine",
    ["reason"],
)
UNSAFE_ACTIONS = Counter(
    "aegis_unsafe_actions_total",
    "Total unsafe/forbidden actions attempted",
    ["action"],
)


@dataclass
class PolicyEvaluationResult:
    allowed: bool
    requires_human_approval: bool
    risk_level: RiskLevel
    rejection_reason: Optional[str] = None
    auto_approved: bool = False


# ── Policy Configuration ──────────────────────────────────────────────────────
FORBIDDEN_ACTIONS = {
    RemediationAction.DELETE_RESOURCE,
    RemediationAction.DATABASE_MUTATION,
}

RISK_TABLE: dict[RemediationAction, RiskLevel] = {
    RemediationAction.RESTART_POD: RiskLevel.LOW,
    RemediationAction.SCALE_DEPLOYMENT: RiskLevel.LOW,
    RemediationAction.ROLLBACK_DEPLOYMENT: RiskLevel.MEDIUM,
    RemediationAction.CHANGE_CONFIG: RiskLevel.HIGH,
    RemediationAction.DELETE_RESOURCE: RiskLevel.FORBIDDEN,
    RemediationAction.DATABASE_MUTATION: RiskLevel.FORBIDDEN,
}

# Actions that require human approval
REQUIRES_APPROVAL: set[RemediationAction] = {
    RemediationAction.ROLLBACK_DEPLOYMENT,
    RemediationAction.CHANGE_CONFIG,
}

# Scale-up limit: never auto-approve more than this replica count
MAX_AUTO_SCALE_REPLICAS = 10
MIN_AUTO_SCALE_REPLICAS = 1


def evaluate_policy(
    plan: RemediationPlan,
    requesting_agent: str = "remediation_agent",
) -> PolicyEvaluationResult:
    """
    Evaluate a remediation plan against Aegis security policy.

    This function is pure and deterministic. It does NOT call any external API.
    """
    action = plan.action
    namespace = plan.namespace
    target = plan.target

    # ── 1. Forbidden action check ─────────────────────────────────────────────
    if action in FORBIDDEN_ACTIONS:
        reason = f"Action {action.value!r} is permanently forbidden by policy"
        logger.warning(
            "Policy: FORBIDDEN action blocked",
            action=action.value,
            incident_id=plan.incident_id,
            plan_id=plan.plan_id,
            agent=requesting_agent,
        )
        POLICY_REJECTIONS.labels(reason="forbidden_action").inc()
        UNSAFE_ACTIONS.labels(action=action.value).inc()
        return PolicyEvaluationResult(
            allowed=False,
            requires_human_approval=False,
            risk_level=RiskLevel.FORBIDDEN,
            rejection_reason=reason,
        )

    # ── 2. Namespace authorization ────────────────────────────────────────────
    allowed_namespaces = settings.allowed_namespaces
    if namespace not in allowed_namespaces:
        reason = f"Namespace {namespace!r} is not in the allowed list {allowed_namespaces}"
        logger.warning(
            "Policy: namespace not allowed",
            namespace=namespace,
            incident_id=plan.incident_id,
            plan_id=plan.plan_id,
        )
        POLICY_REJECTIONS.labels(reason="namespace_not_allowed").inc()
        return PolicyEvaluationResult(
            allowed=False,
            requires_human_approval=False,
            risk_level=RiskLevel.HIGH,
            rejection_reason=reason,
        )

    # ── 3. Deployment / target authorization ──────────────────────────────────
    allowed_deployments = settings.allowed_deployments
    if target not in allowed_deployments:
        reason = f"Target {target!r} is not in the allowed deployments list {allowed_deployments}"
        logger.warning(
            "Policy: target not allowed",
            target=target,
            incident_id=plan.incident_id,
            plan_id=plan.plan_id,
        )
        POLICY_REJECTIONS.labels(reason="target_not_allowed").inc()
        return PolicyEvaluationResult(
            allowed=False,
            requires_human_approval=False,
            risk_level=RiskLevel.HIGH,
            rejection_reason=reason,
        )

    # ── 4. Parameter bounds checking ─────────────────────────────────────────
    if action == RemediationAction.SCALE_DEPLOYMENT:
        requested_replicas = plan.parameters.get("replicas", 2)
        if not isinstance(requested_replicas, int):
            reason = f"SCALE_DEPLOYMENT 'replicas' parameter must be an integer, got {type(requested_replicas).__name__}"
            POLICY_REJECTIONS.labels(reason="invalid_parameter").inc()
            return PolicyEvaluationResult(
                allowed=False,
                requires_human_approval=False,
                risk_level=RiskLevel.HIGH,
                rejection_reason=reason,
            )
        if requested_replicas > MAX_AUTO_SCALE_REPLICAS:
            reason = f"Requested replicas {requested_replicas} exceeds maximum allowed {MAX_AUTO_SCALE_REPLICAS}"
            POLICY_REJECTIONS.labels(reason="replica_limit_exceeded").inc()
            return PolicyEvaluationResult(
                allowed=False,
                requires_human_approval=False,
                risk_level=RiskLevel.HIGH,
                rejection_reason=reason,
            )
        if requested_replicas < MIN_AUTO_SCALE_REPLICAS:
            reason = f"Requested replicas {requested_replicas} below minimum {MIN_AUTO_SCALE_REPLICAS}"
            POLICY_REJECTIONS.labels(reason="replica_minimum_violated").inc()
            return PolicyEvaluationResult(
                allowed=False,
                requires_human_approval=False,
                risk_level=RiskLevel.HIGH,
                rejection_reason=reason,
            )

    # ── 5. Risk level and approval determination ───────────────────────────────
    risk_level = RISK_TABLE.get(action, RiskLevel.HIGH)
    requires_approval = action in REQUIRES_APPROVAL

    logger.info(
        "Policy evaluation: ALLOWED",
        action=action.value,
        target=target,
        namespace=namespace,
        risk_level=risk_level.value,
        requires_approval=requires_approval,
        incident_id=plan.incident_id,
        plan_id=plan.plan_id,
    )

    return PolicyEvaluationResult(
        allowed=True,
        requires_human_approval=requires_approval,
        risk_level=risk_level,
        rejection_reason=None,
        auto_approved=not requires_approval,
    )
