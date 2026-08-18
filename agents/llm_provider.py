"""
LLM Provider Abstraction

The AI component is isolated behind a clean interface.
The platform supports:
  - openai: Real OpenAI API (requires OPENAI_API_KEY)
  - mock: Deterministic mock that generates realistic-looking RCA
           for testing, CI, and local development without API costs.

The LLM is treated as an UNTRUSTED probabilistic component.
Its output is always validated against Pydantic schemas before use.
Malformed outputs are rejected and recorded in audit_logs.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from common.config.settings import get_settings
from common.events.schemas import EvidenceItem, RootCauseAnalysis
from common.logging.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class LLMProvider(ABC):
    """Abstract LLM provider interface."""

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type | None = None,
    ) -> tuple[str, int, float]:
        """
        Returns: (response_text, tokens_used, cost_usd)
        """
        ...


class OpenAIProvider(LLMProvider):
    """Real OpenAI provider using structured outputs."""

    def __init__(self) -> None:
        import openai
        self._client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type | None = None,
    ) -> tuple[str, int, float]:
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            kwargs: dict[str, Any] = {
                "model": settings.openai_model,
                "messages": messages,
                "max_tokens": settings.llm_max_tokens,
                "temperature": settings.llm_temperature,
                "response_format": {"type": "json_object"},
            }

            response = await self._client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content or ""
            tokens = response.usage.total_tokens if response.usage else 0
            # Approximate cost: $5/1M input + $15/1M output tokens for gpt-4o
            cost = (response.usage.prompt_tokens * 5 + response.usage.completion_tokens * 15) / 1_000_000 if response.usage else 0.0
            return text, tokens, cost

        except Exception as exc:
            logger.error("OpenAI API error", error=str(exc))
            return json.dumps({"error": str(exc)}), 0, 0.0


class MockLLMProvider(LLMProvider):
    """
    Deterministic mock LLM for testing and local development.
    Generates realistic-looking structured RCA based on context keywords.
    This is NOT real intelligence — it pattern-matches context to generate
    plausible structured outputs for demo and testing purposes.
    """

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type | None = None,
    ) -> tuple[str, int, float]:
        # Detect context from prompt keywords
        content_lower = user_prompt.lower()

        if "connection" in content_lower and ("exhaust" in content_lower or "pool" in content_lower):
            root_cause = "database connection pool exhaustion"
            component = "payment"
            confidence = 0.91
            actions = [{"action": "ROLLBACK_DEPLOYMENT", "target": "payment", "namespace": "production", "reason": "Recent deployment likely introduced connection leak"}]
            evidence = [
                {"source": "prometheus", "observation": "DB connection pool at 96% capacity for last 5 minutes", "confidence_contribution": 0.4},
                {"source": "loki", "observation": "Connection pool exhausted errors in payment service logs", "confidence_contribution": 0.35},
                {"source": "kubernetes", "observation": "payment-v42 deployed 8 minutes ago coinciding with spike", "confidence_contribution": 0.16},
            ]
            reasoning = [
                "DB connection utilization exceeded 90% threshold",
                "Error pattern 'connection pool exhausted' found in payment service logs",
                "Deployment of payment-v42 occurred 8 minutes before incident",
                "Checkout service errors are downstream cascading failures from payment",
            ]

        elif "crash" in content_lower or "restart" in content_lower or "oomkilled" in content_lower:
            root_cause = "pod OOMKilled due to memory leak in recent deployment"
            component = "payment"
            confidence = 0.87
            actions = [{"action": "ROLLBACK_DEPLOYMENT", "target": "payment", "namespace": "production", "reason": "Memory leak introduced in recent image"}]
            evidence = [
                {"source": "kubernetes", "observation": "Pod restarted 5 times in last 10 minutes with OOMKilled exit reason", "confidence_contribution": 0.5},
                {"source": "prometheus", "observation": "Memory usage at 512MB before crash (limit: 512MB)", "confidence_contribution": 0.3},
            ]
            reasoning = [
                "Pod restart count exceeded threshold with OOMKilled reason",
                "Memory usage exactly at container limit before each crash",
                "Pattern consistent with memory leak introduced by recent deployment",
            ]

        elif "latency" in content_lower or "slow" in content_lower or "timeout" in content_lower:
            root_cause = "elevated latency due to database slow queries"
            component = "payment"
            confidence = 0.78
            actions = [{"action": "SCALE_DEPLOYMENT", "target": "payment", "namespace": "production", "reason": "Scaling to reduce per-instance load while investigating root cause"}]
            evidence = [
                {"source": "prometheus", "observation": "p95 latency increased from 150ms to 2.3s", "confidence_contribution": 0.35},
                {"source": "loki", "observation": "Slow query log entries for payment transactions", "confidence_contribution": 0.3},
                {"source": "tempo", "observation": "Database span duration 85% of total request time in traces", "confidence_contribution": 0.13},
            ]
            reasoning = [
                "p95 latency spike correlates with database query time",
                "Trace waterfall shows 85% of request time in database span",
                "No CPU saturation suggests query efficiency issue",
            ]

        elif "deploy" in content_lower or "rollout" in content_lower:
            root_cause = "bad deployment introducing 500 errors"
            component = "payment"
            confidence = 0.93
            actions = [{"action": "ROLLBACK_DEPLOYMENT", "target": "payment", "namespace": "production", "reason": "New deployment correlated with error rate spike"}]
            evidence = [
                {"source": "prometheus", "observation": "Error rate spiked from 0.1% to 45% immediately after deployment", "confidence_contribution": 0.5},
                {"source": "kubernetes", "observation": "payment-v43 deployed 3 minutes ago", "confidence_contribution": 0.3},
                {"source": "loki", "observation": "NullPointerException in new code path", "confidence_contribution": 0.13},
            ]
            reasoning = [
                "Error rate correlated exactly with deployment timestamp",
                "Stack traces point to new code path introduced in this version",
                "Rollback to v42 expected to resolve issue",
            ]

        else:
            root_cause = "service degradation — investigating dependencies"
            component = "unknown"
            confidence = 0.55
            actions = [{"action": "RESTART_POD", "target": "payment", "namespace": "production", "reason": "Low-risk restart to clear transient state"}]
            evidence = [
                {"source": "prometheus", "observation": "Error rate above threshold for 2 minutes", "confidence_contribution": 0.2},
            ]
            reasoning = [
                "Insufficient evidence to identify specific root cause",
                "Recommending pod restart as low-risk first remediation",
            ]

        result = {
            "root_cause": root_cause,
            "confidence": confidence,
            "suspected_component": component,
            "evidence": evidence,
            "reasoning_steps": reasoning,
            "recommended_actions": actions,
        }

        tokens_estimate = len(user_prompt.split()) + len(json.dumps(result).split())
        cost = tokens_estimate * 0.000005  # fake cost

        logger.info("MockLLM RCA generated", root_cause=root_cause, confidence=confidence)
        return json.dumps(result), tokens_estimate, cost


def get_llm_provider() -> LLMProvider:
    """Factory — returns configured provider based on settings."""
    if settings.llm_provider == "openai" and settings.openai_api_key:
        logger.info("Using OpenAI LLM provider", model=settings.openai_model)
        return OpenAIProvider()
    else:
        if settings.llm_provider == "openai" and not settings.openai_api_key:
            logger.warning("OPENAI_API_KEY not set, falling back to mock LLM provider")
        else:
            logger.info("Using mock LLM provider")
        return MockLLMProvider()
