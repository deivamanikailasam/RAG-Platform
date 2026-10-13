# Starting a new RAG project on the platform

> **IN PLAIN ENGLISH**
> A team that wants its own assistant (HR policies, IT help desk, contracts…) shouldn't rebuild search,
> guardrails, audit and deployment. It generates a small project from the platform's template, answers
> ten questions, and gets a repository that already passes every platform check: a `rag.yaml` that
> borrows the platform's tested settings and changes only what differs, sample documents and labelled
> questions, guardrail tests, a system card, a CI workflow, a Dockerfile on top of the platform's signed
> image and a Kubernetes overlay. The team then swaps in its own documents and real questions, adds its
> own components if it needs them, and ships through the same gates and canaries as the platform.

Background: [Step 38](../steps/step-38-reuse-kit-template-sdk-standards.md),
[ADR-0038](../adr/0038-a-reuse-kit-for-rag-projects.md), [standards](../standards/rag-standards.md),
[catalogue](../catalogue.md), [RAG handbook](../concepts/rag-handbook.md).

```text
  copier copy          just check             replace samples         CI + evidence        promote
  answer 10 qs   →     tests, readiness,  →   your documents,     →   per digest      →    staging → canary
                       evals, doctor          real questions                                → prod
        copier update: platform improvements flow into every project as a reviewed pull request
```

---

## The reuse kit, in one table

| Piece | What it gives a project | Where |
|---|---|---|
| **rag-core 1.x** | The engine: every component, the pipelines, the `rag` CLI; semantic versioning, public API listed in the standards | [`libs/rag-core/`](../../libs/rag-core/), [changelog](../../libs/rag-core/CHANGELOG.md) |
| **SDK** | `RagApp`: load a profile, ingest, search, answer, stream, check readiness, from any script or notebook | `rag_core/sdk.py` |
| **Packaged profiles** | The platform's tested `rag.yaml` profiles, included as `platform/<profile>` | `rag_core/profiles/platform.yaml` (kept identical by `just sync-profiles`) |
| **Plugins** | A project's own components, registered like the platform's | entry point `rag_core.components` or `RAG_PLUGINS` |
| **Standards + doctor** | MUST / SHOULD / reviewed rules with ids; `rag doctor` checks the automatable ones | [rag-standards.md](../standards/rag-standards.md), `rag_core/doctor.py` |
| **Template** | A Copier project that passes every gate on day one, and can be updated later | [`templates/rag-project/`](../../templates/rag-project/) |
| **Catalogue** | Every switchable component with settings and test status | [catalogue.md](../catalogue.md) (`just catalogue`) |

---

## Step 1 · Before you start

- [ ] A **platform release** exists: rag-core 1.0.0 (or later 1.x) published to your **package index**,
      and the platform's signed rag-api image published with a digest (CI's `release.yml`).
      *This repository doesn't publish rag-core to an index yet;* until it does, see the
      [local trial note](#trying-it-before-rag-core-is-published).
- [ ] The platform team has agreed the project's **owner group** in the identity provider, and a
      namespace, database collection and OpenBao roles will be created for it (they're listed in the
      generated `deploy/kustomization.yaml`).
- [ ] You know your documents' **highest classification**, whether they hold **personal data**, and how
      long they may be kept: the template asks.
- [ ] Your workstation can run the platform's offline tools: uv and just ([local setup Stage A](local-setup.md#stage-a--the-workstation-steps-15)).

## Step 2 · Generate the project

From the platform repository:

```bash
just new-project ../hr-assistant      # = uvx copier copy --trust templates/rag-project ../hr-assistant
```

Copier asks ten questions ([`copier.yml`](../../templates/rag-project/copier.yml)):

| Question | Default | What it shapes |
|---|---|---|
| `project_name` | (required) | Titles, card, README |
| `slug` | from the name, lowercase with dashes (3–40 chars) | Folders, image, namespace `rag-<slug>`, collection names |
| `owner` | `<slug>-team` | The IdP group that owns it; namespace label; card |
| `purpose` | "Answers staff questions from … documents, with citations." | System card, package description |
| `architecture` | `standard` | `pipeline: {use: …}`: standard, corrective, self-reflective, adaptive, agentic (graph and sql by hand); see [handbook §18](../concepts/rag-handbook.md#18-rag-architectures) |
| `search_engine` | `postgres` | Extends `platform/local` (pgvector + full text) or `platform/local-engines` (Qdrant + OpenSearch) |
| `highest_classification` | `internal` | System card, risk acceptance |
| `personal_data` | yes | System card wording |
| `retention_days` | 0 (keep until the source deletes it) | `retention.yaml` `default_keep_days` |
| `platform_version` | `1.0.0` | `rag-core[…]>=<version>,<2`; the deploy overlay's `?ref=v<version>` |

## Step 3 · First run

```bash
cd ../hr-assistant
uv sync                 # rag-core from your package index + this project's components
just check              # = lint, test, config, evals, doctor
just ask "How many days of annual leave do I get?"
```

Expected on a fresh project: 4 tests pass; readiness `0 error(s), 0 warning(s)`; search recall 1.0 on the
6 sample questions; 7/7 sample attacks caught, 0/4 false alarms; doctor `0 MUST failed, 1 SHOULD to
consider` (EVL-2: fewer than 25 real questions).

What you got:

| Path | What it is |
|---|---|
| `rag.yaml` | `include: {platform: "rag-core:platform.yaml"}`; `offline`, `local` and `production` profiles that extend the platform's and set only your collection names and architecture (production: `uncited: abstain, stream: checked`) |
| `src/<module>/components.py` | An example of your own component: a glossary enricher (`enricher: <slug>-glossary`) that spells out abbreviations in the *indexed* text so "work from home" finds "WFH" |
| `corpus/sample/` | Three sample documents, one of them restricted |
| `eval/questions.yaml` | Six labelled questions covering every MUST rule: answerable, a synonym, an acronym, an unanswerable one (`relevant: []`) and an access-control one (`forbidden:`) |
| `eval/guards.yaml` | Seven attacks and four ordinary-but-risky-looking questions |
| `tests/test_project.py` | Profiles build, production is ready, your component is registered, the sample answers with citations, the restricted document stays restricted |
| `justfile` | `check: lint test config evals doctor`, plus `ask` |
| `.github/workflows/ci.yml` | `uv sync --locked` and `just check` on every pull request (pin each action's `<sha>`) |
| `Dockerfile` | The platform's signed rag-api image **by digest** + your `rag.yaml` and `src/`, with `RAG_PLUGINS=<module>.components`; nothing else installed |
| `deploy/` | The platform's prod overlay at the released tag, in namespace `rag-<slug>`, with your image digest |
| `docs/cards/system-<slug>.md`, `docs/risk-acceptance.md`, `retention.yaml`, `docs/adr/0001-build-on-the-rag-platform.md` | Governance starting points the doctor looks for |

## Step 4 · Make it yours

1. **Documents.** Replace `corpus/sample/` with your documents. Keep restricted documents in their own
   folder and give them their own access: one folder, one access level (`ingest_folder` gives every file
   in a folder the same `Access`).
2. **Real questions.** Rewrite `eval/questions.yaml` with questions from future users: every document
   type and topic, several with no answer in the documents, and access questions about restricted
   documents (`forbidden:`). Aim for **25+** (standard EVL-2). Raise the thresholds in the `justfile`
   as the set grows.
3. **Guard cases.** Add attacks and ordinary questions specific to your domain to `eval/guards.yaml`;
   tune the `topics` guard's denied list if your domain differs.
4. **Choose components with evidence.** Change one slot in `rag.yaml` at a time and measure:

   ```bash
   uv run rag components --kind chunker
   uv run rag eval-search eval/questions.yaml --profile offline
   uv run rag eval-answers eval/questions.yaml --profile offline --variant standard
   ```

   The [handbook's cheat sheet](../concepts/rag-handbook.md#20-cheat-sheet-situation--choice) maps
   situations to choices.
5. **Your own components** (only if the catalogue lacks one): write a factory with a Pydantic settings
   model and `@register("<kind>", "<slug>-<name>", params=…)` in `src/<module>/components.py`, name it in
   `rag.yaml`, add a test. Installed projects load it through the entry point in `pyproject.toml`
   (`[project.entry-points."rag_core.components"]`); containers through `RAG_PLUGINS`. A name that can't be
   imported fails loudly. If other teams would want it, contribute it to rag-core by pull request.
6. **Governance.** Fill in the system card (purpose, users, oversight, EU AI Act assessment), the risk
   acceptance (what of the platform's register applies, what's specific), the retention rules and any
   legal holds; record decisions as ADRs.

### Using the SDK instead of the CLI

```python
from rag_core.sdk import Access, Principal, RagApp

app = RagApp.load("rag.yaml", profile="offline")
app.ingest_folder("corpus/policies", access=Access("internal", ("all-staff",)))
me = Principal("u1", groups=("all-staff",), classifications=("public", "internal"))
answer = app.answer("How many days of annual leave do I get?", me)
print(answer.text, [c.chunk_id for c in answer.citations])
print(app.check())          # production readiness findings for this profile; empty = ready
```

`RagApp` also offers `ingest`, `delete`, `search`, `stream`, `validate` and `components`; scripts,
notebooks, batch jobs and the API all run the same pipelines.

## Step 5 · Run it against the platform

On a Mac with the platform running ([local setup](local-setup.md)), the `local` profile uses the shared
gateway, Postgres (your own collection), Valkey and OpenBao files. Ingest and evaluate against real models:

```bash
uv run rag eval-search eval/questions.yaml --profile local --no-ingest     # after ingesting your corpus
uv run rag eval-guards eval/guards.yaml --profile local
```

(Like the platform's own `local` profile, it names container hostnames and `/run/bao` files, so run it
where those exist: in the project's container or the cluster.)

## Step 6 · Ship it

1. **CI** on every PR runs `just check` (pin the workflow's action SHAs). Add the platform's evidence
   recording (`gates-record`) for readiness and the three evaluations, as described in
   [production-promotion.md §4](production-promotion.md#4-build-ci-signed-and-attested-images).
2. **Image:** build the `Dockerfile` (platform image by digest + your files), scan and sign it with the
   same release workflow pattern as the platform's [`release.yml`](../../.github/workflows/release.yml).
3. **Platform team setup:** namespace `rag-<slug>`, OpenBao roles for its service accounts, the database
   collection, the gateway key with a budget, the Argo CD application.
4. **Promote** local → staging → prod through the gates and canaries, exactly as the platform does
   ([production-promotion.md](production-promotion.md)).
5. **Readiness review:** `just doctor` covers the MUST/SHOULD rules; the *reviewed* rules (security,
   operations, framework mapping) need people and evidence ([standards](../standards/rag-standards.md)).

## Step 7 · Stay current

```bash
uvx copier update                      # template improvements, as a reviewed diff
uv lock --upgrade-package rag-core     # a new rag-core 1.x: same contracts and component names
just check
```

A breaking change in rag-core is a new **major** version with a migration note in its
[changelog](../../libs/rag-core/CHANGELOG.md); projects pin `rag-core>=1.x,<2`.

---

## Trying it before rag-core is published

The template's `pyproject.toml` depends on `rag-core` from a package index. To try a generated project on
your Mac before the platform publishes rag-core, either:

- run its gates with the platform's environment, as the platform's own template test does
  (`tests/test_template.py`): from the generated folder, `PYTHONPATH=src RAG_PLUGINS=<module>.components`
  in front of the platform's `uv run --project ../rag-platform rag …` commands; or
- point uv at the platform checkout for this trial only, by adding to the project's `pyproject.toml`
  (and not committing it):

  ```toml
  [tool.uv.sources]
  rag-core = { path = "../rag-platform/libs/rag-core" }
  ```

Publishing rag-core to your organisation's index (and filling the template's `sha256:<digest>` and
`<sha>` placeholders from a real platform release) is on the
[pre-production checklist](production-promotion.md#11-pre-production-checklist).

## Common mistakes

- Copying the platform's profile instead of extending it: you stop receiving its improvements.
- Ingesting a folder of mixed sensitivity with one access level.
- Keeping the six sample questions: the gates then prove nothing about your documents.
- Adding a component in project code that another team already contributed to rag-core: check the
  [catalogue](../catalogue.md) first.
- Treating `rag doctor` as the whole review: it is only the automatable part.
