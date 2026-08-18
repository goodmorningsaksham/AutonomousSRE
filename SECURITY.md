# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

---

## AI Safety & Security Model

Aegis implements strict architectural security boundaries:

1. **Untrusted LLM Boundary**: The AI/LLM component is treated as an untrusted, probabilistic advisor. It never receives direct access to the Kubernetes API, shell execution, or database mutations.
2. **Deterministic Policy Engine**: Every remediation proposed by an AI agent must pass through the deterministic Policy Engine before execution.
3. **Hard Forbidden Actions**: High-risk destructive actions such as `DELETE_RESOURCE` and `DATABASE_MUTATION` are permanently blocked at the policy level.
4. **Mandatory Human Approval**: Actions classified as `MEDIUM` or `HIGH` risk (e.g. `ROLLBACK_DEPLOYMENT`, `CHANGE_CONFIG`) require explicit cryptographic or authenticated human approval via the REST API or Dashboard.
5. **Namespace Isolation**: Only explicitly configured namespaces (e.g., `production`, `staging`, `demo`) and target deployments are authorized for remediation actions.
6. **Kubernetes Least Privilege**: Service accounts are scoped with minimal RBAC permissions.

---

## Reporting a Vulnerability

If you discover a security vulnerability in Aegis, please do **NOT** open a public GitHub issue.

Please report vulnerabilities privately to the maintainers or via GitHub Private Vulnerability Reporting.
All reports will be acknowledged within 48 hours and investigated promptly.
