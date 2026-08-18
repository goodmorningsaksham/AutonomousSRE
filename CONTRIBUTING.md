# Contributing to Aegis

Thank you for your interest in contributing to **Aegis**!

Aegis is an event-driven, Kubernetes-native incident response platform designed to automate incident detection, correlation, AI-assisted root cause analysis, deterministic policy evaluation, safe remediation, and recovery verification.

---

## Code of Conduct

Please be respectful and constructive in all issues, pull requests, and discussions.

---

## Development Workflow

### 1. Prerequisites

- **Python**: 3.11+
- **Node.js**: 20+ (for frontend)
- **Docker & Docker Compose**: v2+
- **Make**: (optional but recommended)

### 2. Setting Up Local Environment

```bash
# Clone the repository
git clone https://github.com/goodmorningsaksham/AutonomousSRE.git
cd AutonomousSRE

# Setup Python environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install pytest pytest-asyncio httpx

# Configure environment variables
cp .env.example .env

# Install frontend dependencies
cd frontend && npm install && cd ..
```

### 3. Running Tests

```bash
# Run backend test suite
pytest tests/unit/ tests/integration/ tests/failure/ -v

# Run frontend build
cd frontend && npm run build && cd ..
```

---

## Submitting Pull Requests

1. Create a descriptive feature branch (`git checkout -b feature/your-feature-name`).
2. Ensure all tests pass locally before committing.
3. Follow PEP 8 style conventions for Python and standard TypeScript conventions for frontend code.
4. Open a pull request against `master` describing your changes, motivation, and verification steps.
