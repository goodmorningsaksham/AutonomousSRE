from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    aegis_env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    secret_key: str = "change-me-in-production-at-least-32-chars"

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://aegis:aegis_secret@localhost:5432/aegis"
    database_url_sync: str = "postgresql+psycopg2://aegis:aegis_secret@localhost:5432/aegis"

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Kafka ─────────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_group_id_correlator: str = "aegis-correlator"
    kafka_group_id_investigator: str = "aegis-investigator"
    kafka_group_id_outbox: str = "aegis-outbox-publisher"

    # ── Temporal ──────────────────────────────────────────────────────────────
    temporal_host: str = "localhost"
    temporal_port: int = 7233
    temporal_namespace: str = "default"
    temporal_task_queue: str = "aegis-incident-workflow"

    @property
    def temporal_address(self) -> str:
        return f"{self.temporal_host}:{self.temporal_port}"

    # ── AI / LLM ──────────────────────────────────────────────────────────────
    llm_provider: Literal["openai", "mock"] = "mock"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.1

    # ── Kubernetes ────────────────────────────────────────────────────────────
    kubeconfig: str = ""
    kubernetes_in_cluster: bool = False
    aegis_k8s_allowed_namespaces: str = "production,staging,demo,default"
    aegis_k8s_allowed_deployments: str = "checkout,payment,inventory"

    @property
    def allowed_namespaces(self) -> list[str]:
        return [n.strip() for n in self.aegis_k8s_allowed_namespaces.split(",")]

    @property
    def allowed_deployments(self) -> list[str]:
        return [d.strip() for d in self.aegis_k8s_allowed_deployments.split(",")]

    # ── Observability ─────────────────────────────────────────────────────────
    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"
    tempo_url: str = "http://localhost:3200"
    grafana_url: str = "http://localhost:3000"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "aegis"

    # ── Aegis Services ────────────────────────────────────────────────────────
    aegis_api_port: int = 8000
    aegis_ingestor_port: int = 8001
    correlation_time_window_seconds: int = 300
    verification_observation_window_seconds: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
