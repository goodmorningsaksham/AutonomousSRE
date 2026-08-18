"""
Root Cause Analysis Agent

Collects telemetry evidence from all investigation tools, then
calls the LLM to produce a structured RCA. Validates LLM output
against Pydantic schema — malformed outputs are rejected.

The LLM is treated as an UNTRUSTED probabilistic component.
Evidence collection is deterministic. The LLM only reasons over
pre-collected, sanitized context.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from agents.llm_provider import get_llm_provider
from agents.tools import (
    get_kubernetes_state,
    get_logs,
    get_prometheus_metrics,
    get_recent_deployments,
    get_service_dependencies,
    search_previous_incidents,
    search_runbooks,
)
from common.events.schemas import EvidenceItem, RootCauseAnalysis
from common.logging.logger import get_logger

logger = get_logger(__name__)

RCA_SYSTEM_PROMPT = """
You are an expert Site Reliability Engineer performing root cause analysis on a production incident.

You will receive structured telemetry data from multiple sources (metrics, logs, traces, Kubernetes state, recent deployments, historical incidents).

Your task is to identify the root cause of the incident and recommend specific remediation actions.

IMPORTANT CONSTRAINTS:
- You MUST respond with valid JSON only — no explanatory text outside the JSON object.
- The "action" field in recommended_actions MUST be one of: RESTART_POD, SCALE_DEPLOYMENT, ROLLBACK_DEPLOYMENT
- Do NOT recommend DELETE_RESOURCE, DATABASE_MUTATION, or arbitrary commands
- Set confidence between 0.0 and 1.0 based on evidence quality
- Be specific about which component is the root cause vs which are downstream effects

Required JSON format:
{
  "root_cause": "precise description of root cause",
  "confidence": 0.85,
  "suspected_component": "service or component name",
  "reasoning_steps": ["step 1", "step 2", ...],
  "evidence": [
    {"source": "prometheus", "observation": "...", "confidence_contribution": 0.3},
    ...
  ],
  "recommended_actions": [
    {"action": "ROLLBACK_DEPLOYMENT", "target": "payment", "namespace": "production", "reason": "..."}
  ]
}
"""


async def collect_evidence(
    incident_id: str,
    service: str,
    namespace: str,
) -> dict[str, Any]:
    """
    Runs all investigation tools concurrently and returns aggregated evidence.
    """
    logger.info("Collecting evidence", incident_id=incident_id, service=service)

    # Run all tools concurrently with timeouts
    results = await asyncio.gather(
        get_prometheus_metrics(incident_id, service, namespace),
        get_logs(incident_id, service, namespace),
        get_kubernetes_state(incident_id, service, namespace),
        get_recent_deployments(incident_id, service, namespace),
        search_runbooks(incident_id, f"{service} {namespace} failure"),
        search_previous_incidents(incident_id, f"{service} incident", service),
        return_exceptions=True,
    )

    tool_names = ["prometheus", "loki", "kubernetes", "deployments", "runbooks", "history"]
    evidence: dict[str, Any] = {}

    for name, result in zip(tool_names, results):
        if isinstance(result, Exception):
            logger.warning("Tool failed", tool=name, error=str(result))
            evidence[name] = {"error": str(result)}
        else:
            evidence[name] = result

    evidence["dependencies"] = get_service_dependencies(incident_id, service)

    return evidence


def _build_user_prompt(incident_id: str, service: str, namespace: str, evidence: dict) -> str:
    """Construct the evidence summary for the LLM."""
    lines = [
        f"## Incident: {incident_id}",
        f"## Service: {service} (namespace: {namespace})",
        "",
        "## Telemetry Evidence",
    ]

    # Prometheus metrics
    prom = evidence.get("prometheus", {})
    if "metrics" in prom:
        lines.append("\n### Metrics (Prometheus)")
        for metric, data in prom["metrics"].items():
            if isinstance(data, list) and data:
                lines.append(f"  {metric}: {json.dumps(data[:3])[:300]}")
            elif isinstance(data, dict) and "error" not in data:
                lines.append(f"  {metric}: {json.dumps(data)[:300]}")

    # Logs
    loki = evidence.get("loki", {})
    if "logs" in loki and loki["logs"]:
        lines.append(f"\n### Logs (Loki) — {loki['log_count']} error lines found")
        for entry in loki["logs"][:10]:
            lines.append(f"  [{entry['timestamp']}] {entry['line'][:200]}")

    # Kubernetes state
    if evidence.get("kubernetes"):
        k8s = evidence["kubernetes"]
        pod_count = k8s.get("pod_count", len(k8s.get("pods", [])))
        lines.append(f"\n### Kubernetes State — {pod_count} pods")
        for pod in k8s.get("pods", [])[:5]:
            lines.append(f"  Pod: {pod['name']}, Phase: {pod['phase']}")
            for cs in pod.get("container_statuses", []):
                lines.append(f"    Container {cs['name']}: ready={cs['ready']}, restarts={cs['restart_count']}, state={cs['state']}")
        if k8s.get("deployment"):
            dep = k8s["deployment"]
            lines.append(f"  Deployment: {dep['name']}, replicas: {dep.get('replicas')}, ready: {dep.get('ready_replicas')}, image: {dep.get('image')}")

    # Recent deployments
    deps = evidence.get("deployments", {})
    if deps.get("recent_deployments"):
        lines.append("\n### Recent Deployments")
        for rd in deps["recent_deployments"][:5]:
            lines.append(f"  Revision {rd.get('revision')}: {rd.get('name')} — image: {rd.get('image')} @ {rd.get('created_at')}")

    # Historical incidents
    hist = evidence.get("history", {})
    if hist.get("similar_incidents"):
        lines.append("\n### Similar Historical Incidents")
        for hi in hist["similar_incidents"][:3]:
            lines.append(f"  [{hi['service']}] {hi['title']}: root_cause={hi['root_cause']} → resolution={hi['resolution'][:200]}")

    # Runbooks
    rbs = evidence.get("runbooks", {})
    if rbs.get("runbooks"):
        lines.append("\n### Relevant Runbooks")
        for rb in rbs["runbooks"][:2]:
            lines.append(f"  [{rb['failure_type']}] {rb['title']}: {rb['content'][:300]}")

    # Dependencies
    dep_graph = evidence.get("dependencies", {})
    lines.append(f"\n### Service Dependencies")
    lines.append(f"  {service} depends on: {dep_graph.get('depends_on', [])}")
    lines.append(f"  Services depending on {service}: {dep_graph.get('depended_on_by', [])}")

    return "\n".join(lines)


async def run_rca(
    incident_id: str,
    service: str,
    namespace: str,
) -> tuple[RootCauseAnalysis, list[EvidenceItem], int, float]:
    """
    Main RCA entry point.

    Returns:
        (RootCauseAnalysis, evidence_items, tokens_used, cost_usd)
    """
    start = time.monotonic()
    logger.info("RCA started", incident_id=incident_id, service=service)

    # 1. Collect evidence deterministically
    evidence = await collect_evidence(incident_id, service, namespace)

    # 2. Build prompt
    user_prompt = _build_user_prompt(incident_id, service, namespace, evidence)

    # 3. Call LLM
    llm = get_llm_provider()
    raw_response, tokens, cost = await llm.complete(
        system_prompt=RCA_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    # 4. Validate LLM output — reject malformed responses
    rca: RootCauseAnalysis
    try:
        response_dict = json.loads(raw_response)

        # Validate required fields
        if "root_cause" not in response_dict:
            raise ValueError("Missing 'root_cause' field in LLM response")
        if not isinstance(response_dict.get("confidence"), (int, float)):
            raise ValueError("Missing or invalid 'confidence' field")
        if not (0.0 <= float(response_dict["confidence"]) <= 1.0):
            raise ValueError(f"Confidence {response_dict['confidence']} out of range [0,1]")

        # Validate recommended actions — reject forbidden actions
        ALLOWED_ACTIONS = {"RESTART_POD", "SCALE_DEPLOYMENT", "ROLLBACK_DEPLOYMENT"}
        for action in response_dict.get("recommended_actions", []):
            if action.get("action") not in ALLOWED_ACTIONS:
                logger.warning(
                    "LLM proposed forbidden action — stripped from output",
                    action=action.get("action"),
                    incident_id=incident_id,
                )
                # Strip the forbidden action — the policy engine is the real guardrail
                # but we also clean here for defense in depth

        safe_actions = [
            a for a in response_dict.get("recommended_actions", [])
            if a.get("action") in ALLOWED_ACTIONS
        ]
        response_dict["recommended_actions"] = safe_actions

        # Build typed object
        evidence_items = [
            EvidenceItem(
                source=e.get("source", "unknown"),
                observation=str(e.get("observation", ""))[:500],
                confidence_contribution=float(e.get("confidence_contribution", 0.0)),
            )
            for e in response_dict.get("evidence", [])
        ]

        rca = RootCauseAnalysis(
            root_cause=str(response_dict["root_cause"])[:500],
            confidence=float(response_dict["confidence"]),
            suspected_component=str(response_dict.get("suspected_component", service))[:100],
            reasoning_steps=[str(s)[:300] for s in response_dict.get("reasoning_steps", [])],
            evidence=evidence_items,
            recommended_actions=safe_actions,
        )

    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.error(
            "LLM output validation failed — using fallback RCA",
            incident_id=incident_id,
            error=str(exc),
            raw_response=raw_response[:500],
        )
        # Fallback RCA when LLM output is invalid
        rca = RootCauseAnalysis(
            root_cause="Unable to determine root cause — LLM output malformed",
            confidence=0.1,
            suspected_component=service,
            reasoning_steps=["LLM produced malformed output", f"Error: {str(exc)}"],
            evidence=[],
            recommended_actions=[],
        )
        evidence_items = []

    duration = time.monotonic() - start
    logger.info(
        "RCA completed",
        incident_id=incident_id,
        root_cause=rca.root_cause[:80],
        confidence=rca.confidence,
        duration_seconds=round(duration, 2),
        tokens=tokens,
    )

    return rca, evidence_items, tokens, cost
