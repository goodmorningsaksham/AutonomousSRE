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


def _build_user_prompt(
    incident_id: str,
    service: str,
    namespace: str,
    evidence: dict,
    incident_title: str = "",
    incident_alerts: list[dict] | None = None,
) -> str:
    """Construct the evidence summary for the LLM."""
    lines = [
        f"## Incident: {incident_id}",
        f"## Service Under Investigation: {service} (namespace: {namespace})",
        f"## Incident Title / Symptom: {incident_title or service}",
    ]

    if incident_alerts:
        lines.append("\n### Active Firing Alerts Triggering Incident:")
        for al in incident_alerts:
            lines.append(f"  • Alert: {al.get('name')} (Severity: {al.get('severity')}) — Summary: {al.get('summary')} — Details: {al.get('description')}")

    lines.append("\n## Telemetry Evidence")

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

    # 1b. Fetch active alerts and incident summary from DB
    incident_title = ""
    incident_alerts: list[dict] = []
    try:
        from database.session import AsyncSessionLocal
        from database.models.models import Incident, Alert
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            inc_res = await session.execute(select(Incident).where(Incident.id == incident_id))
            inc_obj = inc_res.scalar_one_or_none()
            if inc_obj:
                incident_title = inc_obj.title
                al_res = await session.execute(select(Alert).where(Alert.incident_id == incident_id))
                incident_alerts = [
                    {
                        "name": a.alert_name,
                        "summary": a.summary or "",
                        "description": a.description or "",
                        "severity": a.severity or "warning",
                    }
                    for a in al_res.scalars().all()
                ]
    except Exception as e:
        logger.warning("Could not fetch alerts for prompt context", error=str(e))

    # 2. Build prompt
    user_prompt = _build_user_prompt(
        incident_id,
        service,
        namespace,
        evidence,
        incident_title=incident_title,
        incident_alerts=incident_alerts,
    )

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

        # Validate and normalize confidence (support float, string numbers, 'High'/'Medium'/'Low')
        conf_raw = response_dict.get("confidence", 0.85)
        if isinstance(conf_raw, str):
            c_str = conf_raw.strip().lower()
            if "high" in c_str:
                confidence_score = 0.90
            elif "med" in c_str:
                confidence_score = 0.70
            elif "low" in c_str:
                confidence_score = 0.40
            else:
                try:
                    num = float(c_str.replace("%", "").strip())
                    confidence_score = num / 100.0 if num > 1.0 else num
                except ValueError:
                    confidence_score = 0.85
        elif isinstance(conf_raw, (int, float)):
            confidence_score = float(conf_raw) / 100.0 if float(conf_raw) > 1.0 else float(conf_raw)
        else:
            confidence_score = 0.85
        confidence_score = max(0.05, min(1.0, confidence_score))

        # Validate recommended actions — reject forbidden actions
        ALLOWED_ACTIONS = {"RESTART_POD", "SCALE_DEPLOYMENT", "ROLLBACK_DEPLOYMENT"}
        safe_actions = []
        for action in response_dict.get("recommended_actions", []):
            if isinstance(action, dict):
                act_name = str(action.get("action", "")).upper()
                if act_name in ALLOWED_ACTIONS:
                    safe_actions.append(action)
                else:
                    logger.warning(
                        "LLM proposed forbidden or unknown action — stripped from output",
                        action=action.get("action"),
                        incident_id=incident_id,
                    )
            elif isinstance(action, str):
                act_upper = action.upper()
                if "ROLLBACK" in act_upper:
                    safe_actions.append({"action": "ROLLBACK_DEPLOYMENT", "target": service, "namespace": namespace, "reason": action})
                elif "RESTART" in act_upper:
                    safe_actions.append({"action": "RESTART_POD", "target": service, "namespace": namespace, "reason": action})
                elif "SCALE" in act_upper:
                    safe_actions.append({"action": "SCALE_DEPLOYMENT", "target": service, "namespace": namespace, "reason": action})

        if not safe_actions:
            safe_actions = [{"action": "RESTART_POD", "target": service, "namespace": namespace, "reason": "Default safe mitigation"}]

        # Build typed object
        evidence_items = []
        for e in response_dict.get("evidence", []):
            if isinstance(e, dict):
                evidence_items.append(
                    EvidenceItem(
                        source=str(e.get("source", "telemetry")),
                        observation=str(e.get("observation", ""))[:500],
                        confidence_contribution=float(e.get("confidence_contribution", 0.0) or 0.0),
                    )
                )
            elif isinstance(e, str):
                evidence_items.append(
                    EvidenceItem(
                        source="llm_evidence",
                        observation=str(e)[:500],
                        confidence_contribution=0.2,
                    )
                )

        reasoning_list = []
        for s in response_dict.get("reasoning_steps", []):
            reasoning_list.append(str(s)[:400])

        rca = RootCauseAnalysis(
            root_cause=str(response_dict["root_cause"])[:500],
            confidence=confidence_score,
            suspected_component=str(response_dict.get("suspected_component", service))[:100],
            reasoning_steps=reasoning_list,
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
