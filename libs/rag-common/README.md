# rag-common

The first shared library of the RAG platform workspace (Step 4). Services under `services/`
import it instead of copying code. Today it only contains uv's template `hello()` function,
used to prove the workspace works:

```bash
uv run --package rag-common python -c "import rag_common; print(rag_common.hello())"
# Hello from rag-common!
```

Code lives under `src/rag_common/` (the "src layout"), so tests always import the installed package.

## Settings (Step 6)

`rag_common.settings` holds the typed `Settings` class every service uses (pydantic-settings).
Values come from environment variables, or from files in `/run/secrets` (how containers receive
secrets). Secrets are `SecretStr`, so they print as `**********`; read the real value only with
`.get_secret_value()`.

```python
from rag_common.settings import get_settings

settings = get_settings()          # cached: built once per process
settings.demo_token                # SecretStr('**********')
```

## Token verification (Step 17)

`rag_common.auth` checks Keycloak access tokens the same way in every service (API, workers,
evaluation). It is framework-free: no FastAPI inside, just PyJWT.

- `TokenVerifier(OIDCSettings(...)).verify(token)` returns a frozen `Principal`
  (`subject`, `username`, `client_id`, `groups`, `roles`) or raises:
  - `AuthError`: the token is bad (signature, algorithm, issuer, audience, expiry, type `Bearer`,
    calling app `azp`, malformed `groups`/roles). Map it to HTTP 401.
  - `KeyServiceUnavailable`: Keycloak's public keys (JWKS) can't be fetched. Map it to HTTP 503.
- Only `RS256` is accepted (no `none`, no `HS256`), with a 30 s clock leeway.
- Keys are cached for 5 minutes and re-fetched when a token names an unknown `kid` (key rotation);
  PyJWT allows at most one such forced re-fetch every 30 s.

```python
from rag_common.auth import OIDCSettings, TokenVerifier

verifier = TokenVerifier(
    OIDCSettings(
        issuer="http://localhost:8180/realms/rag",  # the token's "iss", exactly
        audience="rag-api",
        jwks_url="http://keycloak:8080/realms/rag/protocol/openid-connect/certs",
        allowed_clients=frozenset({"rag-web", "rag-cli", "ingestion-worker"}),
    )
)
principal = verifier.verify(token)  # never log the token itself
```

## `rag_common.prompts`: the prompt registry (Step 24)

Prompts are versioned YAML files in the repository's `prompts/` folder
(`prompts/<name>/v<N>.yaml`), frozen by the SHA-256 recorded in `prompts/prompts.lock.json`, with
`prompts/labels.yaml` saying which version each environment (production, staging…) runs.

- `Registry.load(root)` validates every file (schema, placeholders, untrusted-variable rules), checks
  every hash against the lock, and checks the labels. Any problem raises `PromptError`.
- `registry.render(name, values, label=...)` fills placeholders in ONE pass, refuses missing,
  unexpected or over-long values, and neutralises an untrusted value's closing tag
  (`</question>` becomes `<\/question>`). The result carries `ref` (`rag-answer@2`) and `sha256`:
  record them with every call that used it.
- `lock_only_grew(old, new)` compares a lock with the one on `main`: entries may be added, never
  changed or removed.

```python
from pathlib import Path

from rag_common.prompts import Registry

registry = Registry.load(Path("prompts"))
r = registry.render("query-instruction", {"query": "hybrid work"}, label="production")
r.ref   # 'query-instruction@1'
r.text  # 'Instruct: …\nQuery:hybrid work'
```

The everyday workflow is the CLI: `just prompts list | lint | new | lock | promote | render | diff`.
