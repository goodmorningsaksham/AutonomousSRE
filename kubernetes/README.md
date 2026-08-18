# Aegis Kubernetes Manifests

This directory contains the Kubernetes manifests for deploying Aegis and the sample demo microservice stack to any Kubernetes cluster (e.g. `kind`, `minikube`, or cloud Kubernetes).

## Manifests

| File | Purpose |
| :--- | :--- |
| `namespaces.yaml` | Declares namespaces: `aegis`, `production`, `staging`, `demo` |
| `rbac.yaml` | Least-privilege ServiceAccount, ClusterRole, and ClusterRoleBinding for Aegis remediation executor |
| `aegis-services.yaml` | Deployments and Services for Aegis core services (`api`, `alert-ingestor`, `correlator`, `investigator`, `outbox-publisher`, `temporal-worker`, `frontend`) |
| `demo-apps.yaml` | Deployments, Services, and ConfigMaps for `checkout`, `payment`, and `inventory` demo microservices |

## Quick Apply

```bash
# 1. Create namespaces
kubectl apply -f namespaces.yaml

# 2. Apply RBAC permissions
kubectl apply -f rbac.yaml

# 3. Deploy demo microservices
kubectl apply -f demo-apps.yaml

# 4. Deploy Aegis platform services
kubectl apply -f aegis-services.yaml
```
