# rag-common

The first shared library of the RAG platform workspace (Step 4). Services under `services/`
import it instead of copying code. Today it only contains uv's template `hello()` function,
used to prove the workspace works:

```bash
uv run --package rag-common python -c "import rag_common; print(rag_common.hello())"
# Hello from rag-common!
```

Code lives under `src/rag_common/` (the "src layout"), so tests always import the installed package.
