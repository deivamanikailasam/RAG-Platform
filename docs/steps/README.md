# Step-by-step build notes

One write-up per chapter of the *Project 0 · RAG Platform Foundation* build guide
(source PDFs in [`docs/source/`](../source/)). Each write-up follows the guide's section pattern
(At a glance → The big idea → … → Recap) and ends with the files that step added to this repository.

The guide's project folder `~/dev/rag-platform/` is the root of this repository.

Phases: **A** Workstation · **B** Model serving · **C** Data stores · **D** Identity & policy ·
**E** Observability · **F** Audit & governance · **G** Quality & delivery · **H** RAG core ·
**I** Production & reuse.

| Step | Title | Phase | Write-up |
|---:|---|---|---|
| 1 | Homebrew and the Brewfile | A · Workstation | [step-01-homebrew-brewfile.md](step-01-homebrew-brewfile.md) |
| 2 | Python toolchain with uv | A · Workstation | [step-02-python-uv.md](step-02-python-uv.md) |
| 3 | Container runtime: native models, containerised services | A · Workstation | [step-03-container-runtime.md](step-03-container-runtime.md) |
| 4 | Repository, git conventions and your first ADRs | A · Workstation | [step-04-repository-git-adrs.md](step-04-repository-git-adrs.md) |
| 5 | Linting, formatting and pre-commit hooks | A · Workstation | [step-05-linting-formatting-pre-commit.md](step-05-linting-formatting-pre-commit.md) |
| 6 | Local secrets handling | A · Workstation | [step-06-local-secrets.md](step-06-local-secrets.md) |
| 7 | Serving both Qwen models with mlx-lm | B · Model serving | [step-07-model-serving-mlx-lm.md](step-07-model-serving-mlx-lm.md) |
| 8 | Embedding and reranker servers | B · Model serving | [step-08-embedding-reranker-servers.md](step-08-embedding-reranker-servers.md) |
