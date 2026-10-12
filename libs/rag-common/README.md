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
