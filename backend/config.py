"""
ELOS — Configurações centralizadas via pydantic-settings
Lê do arquivo .env ou variáveis de ambiente do sistema
"""
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Aplicação ─────────────────────────────────────────────
    app_env: Literal["development", "staging", "production", "testing"] = "development"
    app_secret_key: str
    app_version: str = "1.0.0"
    debug: bool = False
    allowed_origins: list[str] = ["http://localhost:3000"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",")]
        return v

    # ── Neo4j ─────────────────────────────────────────────────
    neo4j_uri: str
    neo4j_user: str = "neo4j"
    neo4j_password: str
    neo4j_database: str = "neo4j"

    # ── Supabase ──────────────────────────────────────────────
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_jwt_secret: str

    # ── PostgreSQL (audit_log) ─────────────────────────────────
    database_url: str

    # ── Redis / Celery ────────────────────────────────────────
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str

    # ── LGPD / Criptografia ───────────────────────────────────
    encryption_key_b64: str          # AES-256-GCM key (base64)
    cpf_hash_salt: str               # Per-instance salt — NUNCA alterar em produção

    # ── RNDS ──────────────────────────────────────────────────
    rnds_uf: str = "PE"
    rnds_auth_url: str
    rnds_fhir_url: str
    rnds_client_id: str
    rnds_cert_path: str = ""          # obrigatório em produção; vazio em homologação/teste
    rnds_cert_password: str = ""      # obrigatório em produção
    rnds_env: Literal["homologacao", "producao"] = "homologacao"

    # ── e-SUS PEC ─────────────────────────────────────────────
    esus_base_url: str = ""           # URL base do servidor e-SUS PEC
    esus_username: str = ""
    esus_password: str = ""
    esus_poll_interval_seconds: int = 1800

    # ── SISREG ────────────────────────────────────────────────
    sisreg_url: str = ""
    sisreg_username: str = ""
    sisreg_password: str = ""

    # ── Sentry ────────────────────────────────────────────────
    sentry_dsn: str = ""

    @property
    def is_testing(self) -> bool:
        return self.app_env == "testing"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_rnds_producao(self) -> bool:
        return self.rnds_env == "producao"


@lru_cache
def get_settings() -> Settings:
    """Singleton — lido uma vez, cacheado para todo o processo."""
    return Settings()  # type: ignore[call-arg]
