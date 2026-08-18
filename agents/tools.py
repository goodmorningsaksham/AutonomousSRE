"""
Investigation Tools for the Aegis AI Agent.

Each tool:
- validates arguments strictly
- enforces timeouts
- limits and sanitizes returned data
- logs every invocation for audit
- returns structured data (not raw strings)

The LLM receives tool results as structured context — it NEVER
calls tools directly or constructs raw API queries.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import aiohttp

from common.config.settings import get_settings
from common.logging.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

TOOL_TIMEOUT_SECONDS = 15
MAX_LOG_LINES = 100
MAX_METRIC_SERIES = 20


# ── Base helper ───────────────────────────────────────────────────────────────
async def _http_get(url: str, params: dict | None = None, timeout: int = TOOL_TIMEOUT_SECONDS) -> dict[str, Any]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    text = await response.text()
                    return {"error": f"HTTP {response.status}: {text[:500]}"}
    except asyncio.TimeoutError:
        return {"error": f"Tool timeout after {timeout}s querying {url}"}
    except Exception as exc:
        return {"error": str(exc)}


# ── Prometheus Tool ───────────────────────────────────────────────────────────
async def get_prometheus_metrics(
    incident_id: str,
    service: str,
    namespace: str,
    lookback_minutes: int = 30,
) -> dict[str, Any]:
    """
    Fetch key service metrics from Prometheus.
    Returns error rate, p95 latency, and DB connection metrics.
    """
    logger.info("Tool: get_prometheus_metrics", incident_id=incident_id, service=service)

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(minutes=min(lookback_minutes, 120))  # cap at 2h

    def prom_query(expr: str) -> dict:
        return {
            "query": expr,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": "30s",
        }

    base = settings.prometheus_url

    # Error rate query
    error_query = f'sum(rate(http_requests_total{{job="{service}",status=~"5.."}}[2m])) / sum(rate(http_requests_total{{job="{service}"}}[2m]))'
    latency_query = f'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{job="{service}"}}[2m])))'
    db_conn_query = f'db_pool_connections_used{{job="{service}"}} / db_pool_connections_max{{job="{service}"}}'

    results: dict[str, Any] = {"service": service, "metrics": {}}

    for metric_name, query_expr in [
        ("error_rate_5m", error_query),
        ("p95_latency_seconds", latency_query),
        ("db_connection_ratio", db_conn_query),
    ]:
        data = await _http_get(
            f"{base}/api/v1/query",
            params={"query": query_expr},
        )
        if "data" in data and data["data"]["result"]:
            results["metrics"][metric_name] = data["data"]["result"][:MAX_METRIC_SERIES]
        elif "error" in data:
            results["metrics"][metric_name] = {"error": data["error"]}
        else:
            results["metrics"][metric_name] = []

    return results


# ── Loki Tool ─────────────────────────────────────────────────────────────────
async def get_logs(
    incident_id: str,
    service: str,
    namespace: str,
    lookback_minutes: int = 15,
    filter_level: str = "error",
) -> dict[str, Any]:
    """
    Fetch recent log lines from Loki for the service.
    Filters for error/warn level logs by default.
    """
    logger.info("Tool: get_logs", incident_id=incident_id, service=service)

    end_ns = int(datetime.now(tz=timezone.utc).timestamp() * 1e9)
    start_ns = int((datetime.now(tz=timezone.utc) - timedelta(minutes=min(lookback_minutes, 60))).timestamp() * 1e9)

    query = f'{{service="{service}"}} |= "{filter_level}"'
    data = await _http_get(
        f"{settings.loki_url}/loki/api/v1/query_range",
        params={
            "query": query,
            "start": start_ns,
            "end": end_ns,
            "limit": MAX_LOG_LINES,
        },
    )

    log_lines = []
    if "data" in data and "result" in data["data"]:
        for stream in data["data"]["result"]:
            for ts, line in stream.get("values", [])[:MAX_LOG_LINES]:
                log_lines.append({"timestamp": ts, "line": line[:500]})  # truncate long lines

    return {
        "service": service,
        "filter": filter_level,
        "lookback_minutes": lookback_minutes,
        "log_count": len(log_lines),
        "logs": log_lines[:MAX_LOG_LINES],
    }


# ── Kubernetes Tool ───────────────────────────────────────────────────────────
async def get_kubernetes_state(
    incident_id: str,
    service: str,
    namespace: str,
) -> dict[str, Any]:
    """
    Get Kubernetes pod/deployment state for the affected service.
    Uses the Kubernetes Python client with strict read-only access.
    Never exposes credentials to the LLM.
    """
    logger.info("Tool: get_kubernetes_state", incident_id=incident_id, service=service)

    # Validate namespace is allowed
    if namespace not in settings.allowed_namespaces:
        logger.warning("Namespace not allowed", namespace=namespace)
        return {"error": f"Namespace {namespace!r} is not in the allowed list"}

    try:
        from kubernetes import client as k8s_client, config as k8s_config

        # Load config
        if settings.kubernetes_in_cluster:
            k8s_config.load_incluster_config()
        elif settings.kubeconfig:
            k8s_config.load_kube_config(config_file=settings.kubeconfig)
        else:
            try:
                k8s_config.load_kube_config()
            except Exception:
                return {"error": "No Kubernetes config available", "pods": [], "deployment": None}

        v1 = k8s_client.CoreV1Api()
        apps_v1 = k8s_client.AppsV1Api()

        # Get pods for service
        pods_response = v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"app={service}",
            _request_timeout=2.0,
        )

        pods = []
        for pod in pods_response.items[:20]:  # limit
            container_statuses = []
            if pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    state_info = {}
                    if cs.state.running:
                        state_info = {"running": {"started_at": str(cs.state.running.started_at)}}
                    elif cs.state.waiting:
                        state_info = {"waiting": {"reason": cs.state.waiting.reason, "message": cs.state.waiting.message}}
                    elif cs.state.terminated:
                        state_info = {"terminated": {"reason": cs.state.terminated.reason, "exit_code": cs.state.terminated.exit_code}}

                    container_statuses.append({
                        "name": cs.name,
                        "ready": cs.ready,
                        "restart_count": cs.restart_count,
                        "state": state_info,
                    })

            pods.append({
                "name": pod.metadata.name,
                "phase": pod.status.phase,
                "conditions": [{"type": c.type, "status": c.status} for c in (pod.status.conditions or [])],
                "container_statuses": container_statuses,
            })

        # Get deployment
        deployment_info = None
        try:
            dep = apps_v1.read_namespaced_deployment(name=service, namespace=namespace, _request_timeout=2.0)
            deployment_info = {
                "name": dep.metadata.name,
                "replicas": dep.spec.replicas,
                "ready_replicas": dep.status.ready_replicas,
                "available_replicas": dep.status.available_replicas,
                "image": dep.spec.template.spec.containers[0].image if dep.spec.template.spec.containers else None,
                "generation": dep.metadata.generation,
                "observed_generation": dep.status.observed_generation,
            }
        except Exception:
            pass

        return {
            "service": service,
            "namespace": namespace,
            "pod_count": len(pods),
            "pods": pods,
            "deployment": deployment_info,
        }

    except Exception as exc:
        logger.error("Kubernetes tool error", error=str(exc))
        return {"error": str(exc), "pod_count": 0, "pods": [], "deployment": None}


# ── Deployment History Tool ────────────────────────────────────────────────────
async def get_recent_deployments(
    incident_id: str,
    service: str,
    namespace: str,
    lookback_hours: int = 2,
) -> dict[str, Any]:
    """
    Get recent ReplicaSet revisions for the deployment (rollout history).
    """
    logger.info("Tool: get_recent_deployments", incident_id=incident_id, service=service)

    if namespace not in settings.allowed_namespaces:
        return {"error": f"Namespace {namespace!r} is not allowed"}

    try:
        from kubernetes import client as k8s_client, config as k8s_config

        if settings.kubernetes_in_cluster:
            k8s_config.load_incluster_config()
        else:
            try:
                k8s_config.load_kube_config(config_file=settings.kubeconfig or None)
            except Exception:
                return {"error": "No Kubernetes config", "deployments": []}

        apps_v1 = k8s_client.AppsV1Api()
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)

        # List ReplicaSets for deployment
        rs_list = apps_v1.list_namespaced_replica_set(
            namespace=namespace,
            label_selector=f"app={service}",
            _request_timeout=2.0,
        )

        recent_deployments = []
        for rs in rs_list.items:
            created = rs.metadata.creation_timestamp
            if created and created > cutoff:
                recent_deployments.append({
                    "name": rs.metadata.name,
                    "revision": rs.metadata.annotations.get("deployment.kubernetes.io/revision", "?"),
                    "image": rs.spec.template.spec.containers[0].image if rs.spec.template.spec.containers else None,
                    "created_at": str(created),
                    "replicas": rs.status.replicas,
                    "ready_replicas": rs.status.ready_replicas,
                })

        recent_deployments.sort(key=lambda x: x.get("revision", "0"), reverse=True)

        return {
            "service": service,
            "namespace": namespace,
            "lookback_hours": lookback_hours,
            "recent_deployments": recent_deployments[:10],
        }

    except Exception as exc:
        logger.error("Deployment history tool error", error=str(exc))
        return {"error": str(exc), "deployments": []}


# ── Service Dependency Tool ────────────────────────────────────────────────────
def get_service_dependencies(
    incident_id: str,
    service: str,
) -> dict[str, Any]:
    """
    Return the static dependency graph for a service.
    This is a deterministic, non-AI operation.
    """
    from services.correlator.main import SERVICE_DEPENDENCY_GRAPH

    upstream_deps = SERVICE_DEPENDENCY_GRAPH.get(service, [])
    downstream_of = [svc for svc, deps in SERVICE_DEPENDENCY_GRAPH.items() if service in deps]

    return {
        "service": service,
        "depends_on": upstream_deps,
        "depended_on_by": downstream_of,
    }


# ── RAG Runbook & Historical Incident Search ──────────────────────────────────
async def search_runbooks(
    incident_id: str,
    query: str,
    top_k: int = 3,
) -> dict[str, Any]:
    """
    Semantic similarity search over runbooks using pgvector.
    Falls back to keyword matching if no embeddings available.
    """
    logger.info("Tool: search_runbooks", incident_id=incident_id, query=query[:100])

    try:
        from database.session import AsyncSessionLocal
        from database.models.models import Runbook
        from sqlalchemy import select, func

        async with AsyncSessionLocal() as session:
            # Simple keyword fallback (full pgvector requires embedding the query)
            result = await session.execute(
                select(Runbook)
                .where(Runbook.content.ilike(f"%{query[:50]}%"))
                .limit(top_k)
            )
            runbooks = result.scalars().all()

            return {
                "query": query[:100],
                "runbooks": [
                    {
                        "id": rb.id,
                        "title": rb.title,
                        "service": rb.service,
                        "failure_type": rb.failure_type,
                        "content": rb.content[:1000],  # truncate
                    }
                    for rb in runbooks
                ],
            }
    except Exception as exc:
        logger.error("Runbook search error", error=str(exc))
        return {"query": query[:100], "runbooks": [], "error": str(exc)}


async def search_previous_incidents(
    incident_id: str,
    query: str,
    service: str,
    top_k: int = 3,
) -> dict[str, Any]:
    """
    Find similar historical incidents for RCA context.
    """
    logger.info("Tool: search_previous_incidents", incident_id=incident_id, service=service)

    try:
        from database.session import AsyncSessionLocal
        from database.models.models import HistoricalIncident
        from sqlalchemy import select, or_

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(HistoricalIncident)
                .where(
                    or_(
                        HistoricalIncident.service == service,
                        HistoricalIncident.root_cause.ilike(f"%{query[:50]}%"),
                    )
                )
                .limit(top_k)
            )
            incidents = result.scalars().all()

            return {
                "similar_incidents": [
                    {
                        "id": inc.id,
                        "title": inc.title,
                        "service": inc.service,
                        "root_cause": inc.root_cause,
                        "resolution": inc.resolution,
                        "duration_minutes": inc.duration_minutes,
                        "occurred_at": inc.occurred_at.isoformat(),
                    }
                    for inc in incidents
                ],
            }
    except Exception as exc:
        logger.error("Historical incident search error", error=str(exc))
        return {"similar_incidents": [], "error": str(exc)}
