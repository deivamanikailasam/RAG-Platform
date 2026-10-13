"""Configuration: plain values from RAG_API_* environment variables, secrets from files.

Secret files are looked up in /run/secrets (Docker secrets, from SOPS) and /run/bao (written by
OpenBao Agent, Step 28). When a file exists in both, /run/bao wins.
"""

from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from rag_common.secrets import Credentials, CredentialsFile, StaticCredentials


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAG_API_", secrets_dir=["/run/secrets", "/run/bao"]
    )

    oidc_issuer: str  # http://localhost:8180/realms/rag
    oidc_audience: str = "rag-api"
    oidc_jwks_url: str  # http://keycloak:8080/realms/rag/protocol/openid-connect/certs
    allowed_clients: list[str] = ["rag-web", "rag-cli", "ingestion-worker"]

    gateway_url: str = "http://litellm:4000/v1"
    gateway_key: SecretStr  # file /run/secrets/rag_api_gateway_key (or /run/bao, Step 28)
    db_host: str = "rag-db"
    # Database logins: EITHER a credentials file kept fresh by OpenBao Agent (Step 28) OR the old
    # fixed user + password (before the cut-over, or to roll back). The file wins when both are set.
    db_credentials_file: Path | None = None  # /run/bao/rag_db.json
    db_user: str = "rag_app"  # the evaluation harness uses rag_readonly (Step 26)
    db_password: SecretStr | None = None  # file /run/secrets/rag_api_db_password
    # Audit log (Step 23): a separate database, written as the append-only audit_writer role
    audit_db_host: str = "rag-db"
    audit_db_port: int = 5432
    audit_db_credentials_file: Path | None = None  # /run/bao/audit_db.json
    audit_db_password: SecretStr | None = None  # file /run/secrets/rag_api_audit_db_password
    # Prompt registry (Step 24): the folder baked into the image, and which label this environment runs
    prompts_dir: Path = Path("/app/prompts")
    prompt_label: str = "production"  # staging environments set "staging"
    opa_url: str = "http://opa:8181"  # the policy decision point (Step 18)
    opa_token: SecretStr  # file /run/secrets/rag_api_opa_token (or /run/bao, Step 28)
    # Langfuse (Step 22). Leave langfuse_base_url empty to switch LLM tracing off.
    langfuse_base_url: str | None = None  # http://langfuse-web:3000
    langfuse_public_key: str | None = None  # pk-lf-… (identifies the project, not secret)
    langfuse_secret_key: SecretStr | None = None  # file /run/secrets/rag_api_langfuse_secret_key
    langfuse_capture_question: bool = True  # False: record that a question was asked, not its text

    @model_validator(mode="after")
    def _one_login_each(self) -> "Settings":
        if self.db_credentials_file is None and self.db_password is None:
            raise ValueError("set db_credentials_file (OpenBao) or db_password (static)")
        if self.audit_db_credentials_file is None and self.audit_db_password is None:
            raise ValueError(
                "set audit_db_credentials_file (OpenBao) or audit_db_password (static)"
            )
        return self

    def db_credentials(self) -> Credentials:
        if self.db_credentials_file is not None:
            return CredentialsFile(self.db_credentials_file)
        if self.db_password is None:  # pragma: no cover - the validator prevents it
            raise ValueError("no database login configured")
        return StaticCredentials(self.db_user, self.db_password.get_secret_value())

    def audit_db_credentials(self) -> Credentials:
        if self.audit_db_credentials_file is not None:
            return CredentialsFile(self.audit_db_credentials_file)
        if self.audit_db_password is None:  # pragma: no cover
            raise ValueError("no audit database login configured")
        return StaticCredentials("audit_writer", self.audit_db_password.get_secret_value())
