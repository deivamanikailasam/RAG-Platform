"""Configuration: plain values from RAG_API_* environment variables, secrets from files in
/run/secrets."""

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
    opa_url: str = "http://opa:8181"  # the policy decision point (Step 18)
    opa_token: SecretStr  # file /run/secrets/rag_api_opa_token
