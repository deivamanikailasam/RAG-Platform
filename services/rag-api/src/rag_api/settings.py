"""Configuration: plain values from RAG_API_* environment variables, secrets from files in
/run/secrets."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_API_", secrets_dir="/run/secrets")

    oidc_issuer: str  # http://localhost:8180/realms/rag
    oidc_audience: str = "rag-api"
    oidc_jwks_url: str  # http://keycloak:8080/realms/rag/protocol/openid-connect/certs
    allowed_clients: list[str] = ["rag-web", "rag-cli", "ingestion-worker"]

    gateway_url: str = "http://litellm:4000/v1"
    gateway_key: SecretStr  # file /run/secrets/rag_api_gateway_key
    db_host: str = "rag-db"
    db_password: SecretStr  # file /run/secrets/rag_api_db_password
    # Audit log (Step 23): a separate database, written as the append-only audit_writer role
    audit_db_host: str = "rag-db"
    audit_db_port: int = 5432
    audit_db_password: SecretStr  # file /run/secrets/rag_api_audit_db_password
    # Prompt registry (Step 24): the folder baked into the image, and which label this environment runs
    prompts_dir: Path = Path("/app/prompts")
    prompt_label: str = "production"  # staging environments set "staging"
    opa_url: str = "http://opa:8181"  # the policy decision point (Step 18)
    opa_token: SecretStr  # file /run/secrets/rag_api_opa_token
    # Langfuse (Step 22). Leave langfuse_base_url empty to switch LLM tracing off.
    langfuse_base_url: str | None = None  # http://langfuse-web:3000
    langfuse_public_key: str | None = None  # pk-lf-… (identifies the project, not secret)
    langfuse_secret_key: SecretStr | None = None  # file /run/secrets/rag_api_langfuse_secret_key
    langfuse_capture_question: bool = True  # False: record that a question was asked, not its text
