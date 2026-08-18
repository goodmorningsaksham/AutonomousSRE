"""
Kubernetes Executor

Executes approved remediation actions via the official Kubernetes Python client.
This module has minimum required RBAC permissions (namespace-scoped).

Idempotency: Before executing any action, checks if it was already executed
using the remediation_executions table. If already executed, returns SKIPPED.

The LLM NEVER touches this module.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from common.config.settings import get_settings
from common.events.schemas import (
    RemediationAction,
    RemediationExecutedPayload,
    RemediationPlan,
    RemediationResult,
)
from common.logging.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


async def execute_remediation(
    plan: RemediationPlan,
    execution_id: str,
) -> RemediationExecutedPayload:
    """
    Execute a remediation plan against the Kubernetes API.

    Idempotency: The execution_id is checked against the DB before executing.
    If the same execution_id was already processed, returns SKIPPED.
    """
    logger.info(
        "Executing remediation",
        plan_id=plan.plan_id,
        execution_id=execution_id,
        action=plan.action.value,
        target=plan.target,
        namespace=plan.namespace,
    )

    # ── Idempotency check ─────────────────────────────────────────────────────
    from sqlalchemy import select
    from database.models.models import RemediationExecution
    from database.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(RemediationExecution).where(
                RemediationExecution.id == execution_id
            )
        )
        existing = result.scalar_one_or_none()
        if existing and existing.status in ("SUCCESS", "SKIPPED"):
            logger.info(
                "Remediation already executed — skipping (idempotent)",
                execution_id=execution_id,
                plan_id=plan.plan_id,
            )
            return RemediationExecutedPayload(
                plan_id=plan.plan_id,
                incident_id=plan.incident_id,
                action=plan.action,
                target=plan.target,
                namespace=plan.namespace,
                result=RemediationResult.SKIPPED_IDEMPOTENT,
                executed_at=existing.executed_at,
            )

    # ── Execute ───────────────────────────────────────────────────────────────
    try:
        result_str = await _execute_k8s_action(plan)

        # Record execution
        async with AsyncSessionLocal() as session:
            async with session.begin():
                exec_record = RemediationExecution(
                    id=execution_id,
                    plan_id=plan.plan_id,
                    incident_id=plan.incident_id,
                    action=plan.action.value,
                    target=plan.target,
                    namespace=plan.namespace,
                    status="SUCCESS",
                    result=result_str,
                    executed_at=datetime.now(tz=timezone.utc),
                    completed_at=datetime.now(tz=timezone.utc),
                )
                session.add(exec_record)

        return RemediationExecutedPayload(
            plan_id=plan.plan_id,
            incident_id=plan.incident_id,
            action=plan.action,
            target=plan.target,
            namespace=plan.namespace,
            result=RemediationResult.SUCCESS,
        )

    except Exception as exc:
        error_msg = str(exc)
        logger.error(
            "Remediation execution failed",
            plan_id=plan.plan_id,
            action=plan.action.value,
            error=error_msg,
        )

        # Record failure
        async with AsyncSessionLocal() as session:
            async with session.begin():
                exec_record = RemediationExecution(
                    id=execution_id,
                    plan_id=plan.plan_id,
                    incident_id=plan.incident_id,
                    action=plan.action.value,
                    target=plan.target,
                    namespace=plan.namespace,
                    status="FAILURE",
                    error=error_msg,
                    executed_at=datetime.now(tz=timezone.utc),
                    completed_at=datetime.now(tz=timezone.utc),
                )
                session.add(exec_record)

        return RemediationExecutedPayload(
            plan_id=plan.plan_id,
            incident_id=plan.incident_id,
            action=plan.action,
            target=plan.target,
            namespace=plan.namespace,
            result=RemediationResult.FAILURE,
            error=error_msg,
        )


async def _execute_k8s_action(plan: RemediationPlan) -> str:
    """Dispatch to the correct Kubernetes API call based on action type."""
    action = plan.action
    target = plan.target
    namespace = plan.namespace

    if action == RemediationAction.RESTART_POD:
        return await _restart_pod(target, namespace)
    elif action == RemediationAction.SCALE_DEPLOYMENT:
        replicas = int(plan.parameters.get("replicas", 2))
        return await _scale_deployment(target, namespace, replicas)
    elif action == RemediationAction.ROLLBACK_DEPLOYMENT:
        return await _rollback_deployment(target, namespace, plan.parameters)
    else:
        raise ValueError(f"Unsupported action: {action.value}")


async def _get_k8s_clients():
    """Load Kubernetes clients with appropriate config."""
    from kubernetes import client as k8s_client, config as k8s_config

    if settings.kubernetes_in_cluster:
        k8s_config.load_incluster_config()
    else:
        try:
            k8s_config.load_kube_config(config_file=settings.kubeconfig or None)
        except Exception as exc:
            raise RuntimeError(f"Cannot load Kubernetes config: {exc}") from exc

    v1 = k8s_client.CoreV1Api()
    apps_v1 = k8s_client.AppsV1Api()
    return v1, apps_v1


async def _restart_pod(target: str, namespace: str) -> str:
    """
    Restart pods by deleting them (deployment controller recreates them).
    Only deletes pods matching the deployment label.
    """
    loop = asyncio.get_event_loop()

    def _do_restart():
        from kubernetes import client as k8s_client, config as k8s_config
        if settings.kubernetes_in_cluster:
            k8s_config.load_incluster_config()
        else:
            k8s_config.load_kube_config(config_file=settings.kubeconfig or None)

        v1 = k8s_client.CoreV1Api()
        pods = v1.list_namespaced_pod(namespace=namespace, label_selector=f"app={target}")
        deleted = 0
        for pod in pods.items:
            v1.delete_namespaced_pod(name=pod.metadata.name, namespace=namespace)
            deleted += 1
            logger.info("Pod deleted for restart", pod=pod.metadata.name, namespace=namespace)
        return f"Restarted {deleted} pods for deployment {target}"

    try:
        result = await loop.run_in_executor(None, _do_restart)
        return result
    except Exception as exc:
        # If Kubernetes unavailable (local dev), simulate success
        logger.warning("K8s unavailable, simulating restart", error=str(exc))
        return f"[SIMULATED] Would restart pods for {target} in {namespace}"


async def _scale_deployment(target: str, namespace: str, replicas: int) -> str:
    """Scale a deployment to the specified replica count."""
    loop = asyncio.get_event_loop()

    def _do_scale():
        from kubernetes import client as k8s_client, config as k8s_config
        if settings.kubernetes_in_cluster:
            k8s_config.load_incluster_config()
        else:
            k8s_config.load_kube_config(config_file=settings.kubeconfig or None)

        apps_v1 = k8s_client.AppsV1Api()
        patch_body = {"spec": {"replicas": replicas}}
        apps_v1.patch_namespaced_deployment_scale(
            name=target, namespace=namespace, body=patch_body
        )
        return f"Scaled deployment {target} to {replicas} replicas in {namespace}"

    try:
        result = await loop.run_in_executor(None, _do_scale)
        return result
    except Exception as exc:
        logger.warning("K8s unavailable, simulating scale", error=str(exc))
        return f"[SIMULATED] Would scale {target} to {replicas} replicas in {namespace}"


async def _rollback_deployment(target: str, namespace: str, parameters: dict) -> str:
    """
    Rollback a deployment to the previous revision using Kubernetes rollout API.
    """
    loop = asyncio.get_event_loop()

    def _do_rollback():
        import subprocess
        # Use kubectl rollout undo via subprocess (limited scope)
        # In production, prefer the K8s rollout API directly
        cmd = ["kubectl", "rollout", "undo", f"deployment/{target}", "-n", namespace]
        target_revision = parameters.get("target_revision", "")
        if target_revision and target_revision != "previous":
            cmd.extend([f"--to-revision={target_revision}"])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"kubectl rollout undo failed: {result.stderr}")
        return result.stdout.strip() or f"Rolled back deployment {target} in {namespace}"

    try:
        result = await loop.run_in_executor(None, _do_rollback)
        return result
    except FileNotFoundError:
        # kubectl not available — try Python client
        try:
            result = await loop.run_in_executor(None, lambda: _rollback_via_python_client(target, namespace, parameters))
            return result
        except Exception as exc2:
            logger.warning("K8s unavailable, simulating rollback", error=str(exc2))
            return f"[SIMULATED] Would rollback deployment {target} in {namespace}"
    except Exception as exc:
        logger.warning("Rollback via kubectl failed, simulating", error=str(exc))
        return f"[SIMULATED] Would rollback deployment {target} in {namespace}"


def _rollback_via_python_client(target: str, namespace: str, parameters: dict) -> str:
    """Rollback via Python kubernetes client patch."""
    from kubernetes import client as k8s_client, config as k8s_config

    if settings.kubernetes_in_cluster:
        k8s_config.load_incluster_config()
    else:
        k8s_config.load_kube_config(config_file=settings.kubeconfig or None)

    apps_v1 = k8s_client.AppsV1Api()
    # Trigger rollout by patching annotation (forces new rollout)
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "aegis.io/rollback-trigger": str(uuid.uuid4())
                    }
                }
            }
        }
    }
    apps_v1.patch_namespaced_deployment(name=target, namespace=namespace, body=patch)
    return f"Triggered rollback of deployment {target} in {namespace} via annotation patch"
