# Step 38 · The reuse kit: template, SDK, standards and the whole platform

*Step 38 of 38 · Phase I · Production & reuse*

## At a glance

| | |
|---|---|
| **Goal** | Make the next RAG project cheap. A team with a new use case should get a working, tested, standards-compliant project in minutes, write only what is specific to them, and inherit every improvement the platform makes later. This last step also maps everything built in 38 steps onto the areas a RAG platform must cover, with the options for each. |
| **How, in one sentence** | rag-core becomes a versioned library (1.0.0) with an SDK, packaged platform profiles that a project's `rag.yaml` includes and extends, plugins by entry point or environment variable, a `rag doctor` that checks a project against written standards, a generated catalogue of all 94 components, and a Copier project template whose output passes its own tests, quality gates and doctor on the first run. |
| **Time** | About 3 hours. |
| **You'll end up with** | `rag_core.sdk.RagApp`: ingest, search, answer, stream, check, in a few lines · `include: {platform: "rag-core:platform.yaml"}` in any `rag.yaml`; `RAG_PLUGINS` for containers · `rag doctor` and `docs/standards/rag-standards.md` (MUST / SHOULD / reviewed, with ids) · `templates/rag-project`: `just new-project ../hr-assistant`, then `just check` passes · `docs/catalogue.md` (Appendix C), generated and checked in CI; `libs/rag-core/CHANGELOG.md` · the platform's ADRs in `docs/adr/`; 16 new tests; ADR-0038. |
| **New words** | golden path (paved road), project template, scaffolding, SDK (facade), semantic versioning, public API, plugin, standards as code, inner source. |

## The big idea

> **ANALOGY · A FRANCHISE KIT**
> A good franchise doesn't ask each new shop to invent a kitchen. It hands over a kit: the fitted kitchen (the
> platform), the recipe book with exact quantities (the standards), the supplier list (the catalogue of components),
> a checklist inspectors use (the doctor), and a shop template where the owner only chooses the name, the
> menu specials and the opening hours (the project template). When head office improves a recipe, every shop
> gets the update. Each shop is different where it matters and identical where it should be.

### Five layers (Figure 120)

```
  A RAG project (from the template)
  rag.yaml (only what differs) · own components · eval questions and guard cases · system card · retention
  ───────────────────────────────────────────────────────────────────────────────────────────────
  rag-core 1.x (the library)
  contracts · 94 switchable components · pipelines · SDK · evaluations · readiness · doctor · lifecycle
  ───────────────────────────────────────────────────────────────────────────────────────────────
  Platform services
  rag-api (auth, policy, audit, streaming) · model gateway · stores · identity · secrets · telemetry
  ───────────────────────────────────────────────────────────────────────────────────────────────
  Delivery and operations
  CI gates · signed images · Kubernetes overlays · canaries · promotion gates · HA/DR · alerts
  ───────────────────────────────────────────────────────────────────────────────────────────────
  Governance
  risk register · controls with evidence · framework mapping · cards · ADRs · standards
```

A project writes only the top layer: what differs in `rag.yaml`, its own components, its evaluation questions
and guard cases, its system card and retention. Everything below — rag-core, the platform services, delivery and
operations, and governance — is shared, versioned and tested once, for every project.

## What we're doing

1. An SDK so scripts, notebooks, jobs and the API use one entry point.
2. Packaged profiles and includes, so a project's `rag.yaml` holds only its differences.
3. Plugins for a project's own components, installed or copied into the image.
4. Standards as code: written rules with ids, and `rag doctor` to check them.
5. A project template that produces a passing project on the first run.
6. A generated catalogue of every option, and versioning that keeps projects safe across upgrades.
7. The coverage map: every area of a RAG platform, where it lives, and the alternatives.

## Why we're doing this

> **WHY THIS MATTERS**
> Without a reuse kit, the second project copies the first: its config, its quirks, its missing tests. By the fifth
> project there are five ways to chunk, three ways to check access, and one team that still has no evaluation set.
> Each fix has to be made five times, and security reviews start from zero every time.

| Need | How this step meets it |
|---|---|
| Start a project in minutes, correctly | Copier template: answers → a project whose tests, readiness, evaluations and doctor pass |
| Write only what's different | `include` the packaged platform profiles; extend `platform/offline`, `platform/production` |
| Add something the platform lacks | `@register` in the project; entry point, or `RAG_PLUGINS` in a container |
| One way to call the engine | `RagApp`: the same pipelines rag-api uses |
| Know a project meets the bar | `rag doctor` against written standards; MUST rules fail CI |
| Know what's possible | Catalogue generated from the code (Appendix C) |
| Upgrade without breaking projects | Semantic versioning of rag-core; `copier update` for template changes |

> **IN A COMPANY**
> This is a golden path (or "paved road"): the supported way to build a kind of system, which is also the easiest
> way. Platform teams measure it by time to first production release for a new team and by how many projects are
> on the current version. Pair it with an internal developer portal (Backstage software templates can run this
> same Copier template) and an inner-source model: project teams contribute components back to rag-core through
> pull requests, reviewed by the platform team.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| Golden path / paved road | The supported, easiest way to build a certain kind of system, with the right defaults built in. |
| Project template, scaffolding | A generator that creates a new project's files from a few answers. |
| SDK, facade | A small, friendly interface over a bigger system: one object instead of many pipelines. |
| Public API | The parts of a library others rely on: changing them breaks their code. |
| Semantic versioning | MAJOR.MINOR.PATCH: a MAJOR change may break you; MINOR adds; PATCH fixes. |
| Plugin | Code from outside the library that registers itself into it. |
| Standards as code | Rules written down with ids and checked by a program, not only by reviewers. |
| Inner source | Open-source habits inside a company: anyone can propose changes to shared code. |

> **IN PLAIN ENGLISH**
> Until now the platform was one repository that answers questions about one sample handbook. This step turns it
> into a *kit*: a library other teams install (rag-core), a starter project they generate (the template), a rule
> book they follow (the standards) and an inspector that checks the rules (the doctor). A new team answers ten
> questions and gets a project that already passes every check; they then replace the sample documents and
> questions with their own.

## How to do it

### 1 · The SDK

One object over the same pipelines rag-api uses (Steps 31-37): `libs/rag-core/src/rag_core/sdk.py`.

```python
from rag_core.sdk import Access, Principal, RagApp

app = RagApp.load("rag.yaml", profile="offline")
app.ingest_folder("corpus/policies", access=Access("internal", ("all-staff",)))
me = Principal("u1", groups=("all-staff",), classifications=("public", "internal"))
answer = app.answer("How many days of annual leave do I get?", me)
print(answer.text, [c.chunk_id for c in answer.citations])
```

What `RagApp` offers, and which earlier step each method stands on:

| Method | What it does | Built in |
|---|---|---|
| `RagApp.load(path, profile, env)` | A profile from a `rag.yaml`, with `extends`, includes and `RAG__SLOT__PARAM` overrides | 30, 38 |
| `RagApp.from_dict(slots)` | Slots given directly, e.g. in a test | 30 |
| `ingest(uri, access, metadata, force=)` | One source (file:// or s3://): parsed, redacted, chunked, embedded, indexed | 31 |
| `ingest_folder(folder, access)` | Every document under a folder (`.md .txt .html .pdf .docx .csv`…), same access | 31 |
| `delete(uri)` | Remove a source from every store | 31 |
| `search(question, principal, k=, filters=)` | Ranked chunks this person may see, with every score | 32 |
| `answer(question, principal, session_id=)` | A cited, guarded answer, or an honest "I don't know" | 33-35 |
| `stream(...)` | Events: `meta`, `delta`s, `done` with the checked answer | 33 |
| `check()` | Production readiness findings for this profile; empty = ready | 37 |
| `validate()` | Every slot names a real component with valid settings | 30 |
| `RagApp.components(kind)` | What can be switched, and to what | 30 |

Everything is a thin layer over the same pipelines, so a script, a notebook, a batch job and the API behave
identically. The answer pipeline is built once per app because it holds the conversation memory and the cache.
`register`, `Access`, `Principal` and `ComponentError` are re-exported, so a project needs only `rag_core.sdk`.

> **WATCH OUT · ONE FOLDER, ONE ACCESS LEVEL**
> `ingest_folder` gives every file the same access. Keep restricted documents in their own folder and ingest them
> with their own `Access`. The SDK test does exactly that, because the first draft of the test ingested the whole
> handbook as "internal", including the executive pay document.

### 2 · Packaged profiles: a project writes only what differs

rag-core now ships the platform's tested profiles, at `libs/rag-core/src/rag_core/profiles/platform.yaml`. A
project's `rag.yaml` includes them under a name and extends them:

```yaml
version: 1
include: {platform: "rag-core:platform.yaml"}
profiles:
  offline:    {extends: platform/offline, chunker: {max_tokens: 250}}
  production: {extends: platform/production, pipeline: {use: corrective}}
```

The new `config.read()` in `libs/rag-core/src/rag_core/config.py` expands includes before profiles are resolved:

- `rag-core:<file>` means a file shipped inside rag-core (`PACKAGED`); any other value is a path relative to the
  including file.
- Every included profile appears as `<name>/<profile>` (`platform/offline`, `platform/production`…), and an
  included profile's own `extends` is renamed the same way, so `platform/production` still extends
  `platform/local`.
- Includes may nest at most 3 deep; a missing file is a clear error (`include 'x': … not found`).
- The usual merge rules apply on top: the same component → only the settings you name change (`max_tokens: 250`
  keeps `overlap_tokens: 40`); another component → the slot is replaced, not merged
  (`pipeline: {use: corrective}`).

`rag eval-search` and `rag eval-answers` read `rag.yaml` the same way, so a project's evaluations run on its
included profiles too.

The packaged copy is the platform's `rag.yaml` with a 4-line header. A test fails if they differ; after editing
`rag.yaml`, run:

```bash
just sync-profiles      # copies rag.yaml into rag-core's profiles/platform.yaml, keeping the header
```

Projects therefore get the exact profiles the platform tested.

> **TIP**
> A project that wants something the platform profile doesn't have doesn't copy the profile: it extends it and
> changes one slot. When the platform later improves `platform/production` (a new guard, a better reranker), the
> project gets it with the next rag-core release.

### 3 · Plugins: a project's own components

A project registers components the same way the platform does (Step 30). Two ways to load them, both in
`_load_builtins()` in `libs/rag-core/src/rag_core/registry.py`:

- **Installed:** the project's `pyproject.toml` declares an entry point, and rag-core imports it on first use:

  ```toml
  [project.entry-points."rag_core.components"]
  hr_assistant = "hr_assistant.components"
  ```

- **Copied into a container:** an image that copies a project's code next to the platform image without
  installing it names the modules in `RAG_PLUGINS` (comma-separated), e.g.
  `RAG_PLUGINS=hr_assistant.components`. A name that can't be imported raises
  `ComponentError: RAG_PLUGINS names '…', which can't be imported` — failing loudly instead of silently missing a
  component that `rag.yaml` names.

`from rag_core import Container, register` now works too (`rag_core/__init__.py`), which is what a project's
component module imports.

### 4 · Standards, and rag doctor

The standards are written down with ids, levels and how each is checked, in `docs/standards/rag-standards.md`:

- **MUST** rules fail `rag doctor` (and so CI).
- **SHOULD** rules warn.
- *reviewed* rules are checked by people at the production readiness review, with the evidence named.

A summary of the rule book:

| Area | Ids | Level | What |
|---|---|---|---|
| Configuration | CFG-1..5 | MUST | One `rag.yaml` with profiles, including the platform's; an offline profile; a production profile; every profile builds; production passes readiness |
| | PRM-1 | SHOULD | Answers use a registered prompt selected by label |
| | CFG-6 | reviewed | Secrets only from files written by OpenBao Agent |
| Evaluation | EVL-1, 3, 4, 5 | MUST | Labelled questions; unanswerable questions; access-control questions with forbidden documents; guard cases with attacks AND ordinary questions |
| | EVL-2 | SHOULD | 25+ real user questions |
| | CI-1..3 | MUST | CI runs search/answer evaluation, guard evaluation and readiness |
| | EVL-6 | reviewed | Online evaluation per release |
| Security and privacy | SEC-1..6 | reviewed | Auth, policy, audit; access in every store; tenant isolation; redaction and erasure; workload identities; signed, pinned images |
| Operations | OPS-1..4 | reviewed | Gated promotion and canaries; SLOs and runbooks; backups with drills; cards and ADRs |
| Governance | GOV-1..4 | SHOULD | System card; risk acceptance; retention rules; decision records |
| | GOV-5 | reviewed | Mapping to NIST AI RMF, ISO/IEC 42001, EU AI Act, privacy law |

The **Versioning** section of the standards fixes rag-core's public API: the contracts (`rag_core.contracts`,
`rag_core.types`), the SDK (`rag_core.sdk`), the CLI, component kind/name/setting names, the `rag.yaml` format and
the packaged profiles. A breaking change to any of these is a new MAJOR version, announced in
`libs/rag-core/CHANGELOG.md` with a migration note. Projects pin `rag-core>=1.x,<2`.

`rag doctor` (`libs/rag-core/src/rag_core/doctor.py`) checks the automatable rules. It **reads files only**: no
services, no model calls, so it runs anywhere CI does. Each rule is a small function registered with `@rule` that
yields `Result(rule, level, ok, message, fix)`; every failure carries a fix.

| Rule function | Checks | How |
|---|---|---|
| `config_profiles` | CFG-1..4 | `rag.yaml` read with includes; the project's own profiles (not `platform/…`); an offline/test/ci profile; a production/prod profile; `validate()` per profile |
| `production_ready` | CFG-5, PRM-1 | `readiness.check()` on the production profile; the generator is `llm` with a `prompt_label` (or not an LLM at all) |
| `search_eval` | EVL-1..4 | YAML files under `eval/`, `examples/eval/`, `evals/` with `questions:`; counts; `relevant: []`; `forbidden:` |
| `guard_eval` | EVL-5 | YAML files with `cases:`; `expect` block/redact/flag vs allow |
| `ci_gates` | CI-1..3 | `.github/workflows/*`, `.gitlab-ci.yml`, `justfile`, `Makefile` mention `eval-search`/`eval-answers`, `eval-guards`, `readiness` |
| `governance` | GOV-1..4 | `docs/cards/system-*.md`, a risk register or `docs/risk-acceptance.md`, a `retention.yaml`, `docs/adr/*.md` |

```bash
uv run rag doctor .                 # or: just doctor
uv run rag doctor ../hr-assistant --json
```

The platform checked against its own standards:

```text
ok   CFG-1        MUST   rag.yaml has 5 profile(s)
ok   CFG-2        MUST   a profile that runs with no services (offline/test/ci): offline
ok   CFG-3        MUST   a production profile: production
ok   CFG-4        MUST   profile 'local' builds
ok   CFG-4        MUST   profile 'local-engines' builds
ok   CFG-4        MUST   profile 'local-v2' builds
ok   CFG-4        MUST   profile 'offline' builds
ok   CFG-4        MUST   profile 'production' builds
ok   CFG-5        MUST   production profile passes readiness
ok   PRM-1        SHOULD answers use a registered prompt with a label
ok   EVL-1        MUST   25 labelled question(s) in 1 file(s)
ok   EVL-2        SHOULD 25 questions (25+ recommended)
ok   EVL-3        MUST   1 question(s) with no answer in the documents
ok   EVL-4        MUST   1 access-control question(s) (forbidden documents)
ok   EVL-5        MUST   guard cases: 23 attack(s), 12 ordinary question(s)
ok   CI-1         MUST   CI runs search/answer evaluation
ok   CI-2         MUST   CI runs guardrail evaluation
ok   CI-3         MUST   CI runs production readiness
ok   GOV-1        SHOULD a system card (what it is for, limits, data)
ok   GOV-2        SHOULD a risk register or acceptance of the platform's
ok   GOV-3        SHOULD retention rules for this project's documents
ok   GOV-4        SHOULD decision records

22 ok, 0 MUST failed, 0 SHOULD to consider
```

The platform passes everything, including GOV-4, now that its ADRs live in `docs/adr/` next to the code. (The
guide shows 4 profiles and 21 results; this repository has a fifth, `local-v2`, from Step 36's blue/green
re-index, hence one more CFG-4 line.)

> **WATCH OUT**
> The doctor is the *automatable* part of the standards, not the whole review. The *reviewed* rules — security,
> operations, framework mapping — still need people and evidence at the production readiness review.

### 5 · The project template

```
  copier copy            just check              replace samples          CI + evidence          promote
  answer 10 questions →  tests, readiness,    →  your documents,       →  per digest          →  staging → canary
                         evals, doctor           real questions                                  → prod

        copier update: platform improvements flow into every project as a reviewed pull request
```

*Figure 121. From nothing to production.* `copier copy` asks ten questions; `just check` runs tests, readiness,
evaluations and doctor; the team replaces the samples with its documents and real questions; CI records evidence per
digest; promotion goes through staging and a canary to prod. `copier update` later brings platform improvements as
a reviewed pull request.

The template lives in `templates/rag-project/`:

```
templates/rag-project/
├── copier.yml
└── template/
    ├── .github/workflows/ci.yml.jinja
    ├── .gitignore
    ├── Dockerfile.jinja
    ├── README.md.jinja
    ├── corpus/sample/getting-started.md.jinja
    ├── corpus/sample/leave.md
    ├── corpus/sample/salaries-restricted.md
    ├── deploy/kustomization.yaml.jinja
    ├── deploy/namespace.yaml.jinja
    ├── docs/adr/0001-build-on-the-rag-platform.md.jinja
    ├── docs/cards/system-{{slug}}.md.jinja
    ├── docs/risk-acceptance.md.jinja
    ├── eval/guards.yaml
    ├── eval/questions.yaml.jinja
    ├── justfile.jinja
    ├── pyproject.toml.jinja
    ├── rag.yaml.jinja
    ├── retention.yaml.jinja
    ├── src/{{module}}/__init__.py.jinja
    ├── src/{{module}}/components.py.jinja
    ├── tests/test_project.py.jinja
    └── {{_copier_conf.answers_file}}.jinja
```

Files ending in `.jinja` are rendered with the answers; the others are copied as they are.

**The questions** (`copier.yml`):

| Question | Default | What it shapes |
|---|---|---|
| `project_name` | (required) | Titles, card, README, the component's summary |
| `slug` | from the name, lowercase with dashes | Folders, images, namespace `rag-<slug>`, collections; validated: 3-40 characters of lowercase letters, digits and dashes |
| `module` | slug with underscores (not asked) | The Python package `src/<module>` |
| `owner` | `<slug>-team` | The identity-provider group that owns it; namespace label; card |
| `purpose` | "Answers staff questions from … documents, with citations." | System card, `pyproject.toml` description |
| `architecture` | `standard` | `pipeline: {use: …}` (standard, corrective, self-reflective, adaptive, agentic; graph and sql by hand) |
| `search_engine` | `postgres` | `platform/local` (pgvector + full text) or `platform/local-engines` (Qdrant + OpenSearch) |
| `highest_classification` | `internal` | System card and risk acceptance |
| `personal_data` | yes | System card wording (pseudonymised vs safety net) |
| `retention_days` | 0 (keep until the source deletes) | `retention.yaml` `default_keep_days` |
| `platform_version` | `1.0.0` | `rag-core[…]>=<version>,<2`; the deploy overlay's `?ref=v<version>` |

**What the generated project contains:**

- `rag.yaml` — includes the platform and changes only names and the architecture: `offline` extends
  `platform/offline`; `local` extends `platform/local` or `platform/local-engines` with the project's own
  collection/index names; `production` extends `platform/production` with `uncited: abstain, stream: checked`.
- `pyproject.toml` — depends on `rag-core[postgres,valkey,pdf,docx]>=1.0.0,<2`, declares the
  `rag_core.components` entry point for `<module>.components`, and sets ruff and pytest.
- `src/<module>/components.py` — an example of a project's own component: a **glossary enricher**,
  `enricher: <slug>-glossary`, that appends the spelled-out form of the organisation's abbreviations to each chunk's
  *indexed* text (so a search for "work from home" finds a chunk that only says "WFH") while the chunk is still
  shown and cited as written.
- `eval/questions.yaml` — six samples that exercise every MUST rule: answerable questions (including a synonym and
  an acronym), an unanswerable one (`relevant: []`) and an access question about a restricted document someone may
  not see (`forbidden: [salaries-restricted.md]`).
- `eval/guards.yaml` — seven attacks (override, prompt reveal, PII, legal advice, a poisoned document, a secret in
  an answer, an invented claim) and four ordinary cases that look risky but must pass.
- `justfile` — `check: lint test config evals doctor`, plus `ask`.
- `.github/workflows/ci.yml` — `uv sync --locked` and `just check` on every pull request (pin each action's
  `<sha>`, as the platform does in Step 27).
- `tests/test_project.py` — every profile builds and production is ready; the project's component is registered;
  the sample corpus answers "20 days" with citations; the restricted document stays restricted.
- `Dockerfile` — the platform's signed rag-api image by digest, plus `rag.yaml` and `src/`, with
  `RAG_PLUGINS=<module>.components`. Nothing else is installed.
- `deploy/kustomization.yaml` and `deploy/namespace.yaml` — the platform's prod overlay at the released tag, in
  namespace `rag-<slug>` (restricted pod security, `rag-platform/policy: enforced`), with the project's image
  digest set by promotion pull requests.
- Governance starting points the doctor's SHOULD rules look for: `docs/cards/system-<slug>.md`,
  `docs/risk-acceptance.md`, `retention.yaml`, `docs/adr/0001-build-on-the-rag-platform.md`.
- A `README.md` (start commands, where things are, how to change things), sample documents and a `.gitignore`.

Make one (on your Mac):

```bash
just new-project ../hr-assistant      # uvx copier copy --trust templates/rag-project ../hr-assistant
cd ../hr-assistant
uv sync
just check
```

The generated project, first run (answers: "HR policy assistant", defaults):

```text
$ uv run pytest -q
4 passed

$ uv run rag config readiness --profile production
profile 'production': 0 error(s), 0 warning(s)

$ uv run rag eval-search eval/questions.yaml --profile offline --fail-under recall=0.8
6 questions, profile 'offline', k=5
variant                             recall@5    MRR   nDCG@5  leaks  p50 ms
as-configured                          1.000  1.000    1.000      0     1.9

$ uv run rag eval-guards eval/guards.yaml --profile offline
11 cases: 7 attacks, 4 benign
caught               7/7          catch rate 1.000
false alarms 0/4                  false positive rate 0.000

$ uv run rag eval-answers eval/questions.yaml --profile offline --variant standard --fail-under abstain_ok=1
architecture           ctx recall  answered  cite hit  abstain ok  grounded  leaks  p50 ms
standard                    1.000     0.750     0.750       1.000     1.000      0     2.9

$ uv run rag doctor .
...
warn EVL-2        SHOULD 6 questions (25+ recommended)
                         fix: add real questions from users; aim for every document type and tag
...
19 ok, 0 MUST failed, 1 SHOULD to consider
```

The one warning is deliberate: six sample questions are not enough, and the doctor says so until the team adds real
ones.

> **WATCH OUT · THE LICENCE GATE CAUGHT THE TEMPLATE TOOL**
> The first version added Copier as a development dependency. The licence check from Step 27 then failed: one of
> Copier's own dependencies (`jinja2-ansible-filters`) is GPL-3.0, which the policy denies. Copier is a tool we run
> to generate files, not code we ship, so it now runs isolated with `uvx copier` and never enters the lock file.
> That's the policy working: it forced a deliberate decision instead of a silent one.

### 6 · The catalogue, and versioning

`scripts/catalogue.py` writes `docs/catalogue.md` from the component registry itself (`describe()`): every
component in every kind, in pipeline order (token counting → parsing → … → architecture → graph store → LLMs),
with what it does, its settings and defaults, the extras it needs and how it was tested (**live** = tested against
the real service; **mocked** = tested with a stand-in; **reference** = written to the documented API, not run
here). Because it is generated, it can't drift from the code: a new component appears the moment it is registered.

```bash
just catalogue            # write docs/catalogue.md
just catalogue --check    # fail if it is out of date (run by `just ci-config` in CI)
```

The output is Appendix C of the guide: **94 components in 24 kinds**.

`libs/rag-core/CHANGELOG.md` starts at **1.0.0**, the first stable release, whose public API is fixed for 1.x; the
library's `pyproject.toml` and `rag_core.__version__` say `1.0.0`.

The justfile's Step 38 recipes:

| Recipe | What it does |
|---|---|
| `just new-project dest` | `uvx copier copy --trust templates/rag-project <dest>` |
| `just doctor [path]` | `uv run rag doctor <path>` (default: this repository) |
| `just catalogue [--check]` | Generate or check `docs/catalogue.md` |
| `just sync-profiles` | Copy `rag.yaml` into rag-core's packaged `profiles/platform.yaml` |

`just ci-config` now ends with `just doctor` and `just catalogue --check`.

### 7 · Test it

```bash
just audit-test            # everything (with the Postgres-backed tests)
just doctor
just catalogue --check
```

The new tests:

```text
libs/rag-core/tests/test_sdk.py::test_ingest_search_answer_in_a_few_lines PASSED
libs/rag-core/tests/test_sdk.py::test_access_is_enforced_through_the_sdk PASSED
libs/rag-core/tests/test_sdk.py::test_check_validate_and_components PASSED
libs/rag-core/tests/test_sdk.py::test_a_project_includes_the_platform_profiles PASSED
libs/rag-core/tests/test_sdk.py::test_packaged_profiles_are_the_platforms PASSED
libs/rag-core/tests/test_sdk.py::test_plugins_named_in_the_environment PASSED
libs/rag-core/tests/test_doctor.py::test_the_platform_meets_every_must PASSED
libs/rag-core/tests/test_doctor.py::test_an_empty_folder_fails_and_says_what_to_do PASSED
libs/rag-core/tests/test_doctor.py::test_missing_abstention_and_access_questions PASSED
libs/rag-core/tests/test_doctor.py::test_a_production_profile_with_stand_ins_fails PASSED
libs/rag-core/tests/test_doctor.py::test_cli PASSED
tests/test_template.py::test_generated_project_passes_its_gates[HR policy assistant] PASSED
tests/test_template.py::test_generated_project_passes_its_gates[IT Helpdesk] PASSED
tests/test_template.py::test_generated_project_passes_its_gates[Legal research] PASSED
tests/test_template.py::test_answers_shape_the_project PASSED
tests/test_template.py::test_bad_names_are_refused PASSED
16 passed
```

> **WHAT THE TESTS PROVE**
> - The SDK ingests a folder, searches, answers with citations, streams, and enforces access exactly like rag-api.
> - Includes give a project the platform's profiles with only its changes on top; a missing include is a clear
>   error; the packaged profiles equal the platform's.
> - Plugins named in `RAG_PLUGINS` register; a wrong name fails loudly instead of silently missing a component.
> - The doctor passes the platform, fails an empty folder with a fix for every rule, and catches missing abstention
>   and access questions and a production profile with stand-ins.
> - The template, for three different sets of answers (including Qdrant/OpenSearch, no personal data, a retention
>   period), produces a project whose own lint, tests, readiness, search, guard and answer evaluations and doctor
>   all pass; bad names are refused.

`tests/test_template.py` runs Copier through `uvx --from copier==9.19.0` (skipped if `uvx` is missing) and then
runs each gate in the generated project with the platform's Python, `PYTHONPATH=src` and
`RAG_PLUGINS=<module>.components` (rag-core is not on a package index here, so the project isn't `uv sync`ed).

### 8 · Record the decision

`docs/adr/0038-a-reuse-kit-for-rag-projects.md` (ADR-0038): rag-core 1.0.0 with semantic versioning; packaged
platform profiles included and extended by projects; project components as plugins (entry point or `RAG_PLUGINS`)
with contributions back by pull request; standards with ids checked by `rag doctor` in every project's CI; a Copier
template run as an isolated tool with `copier update`; a catalogue generated from the registry. Alternatives
considered: copying an example project (drift, no path for improvements), Cookiecutter (no update of existing
projects), a monorepo for all projects (coupled releases), platform-as-a-service only (can't extend). Revisit when
projects need a hosted multi-tenant service, or an internal developer portal becomes the entry point.

## The whole platform: coverage map

Every area a production RAG platform needs, where this guide builds it, the options you can switch between (with one
line in `rag.yaml` where it's a component; see `docs/catalogue.md` for every setting), and the alternatives
discussed in each step.

| Area | Built in | What you get (switchable options) | Alternatives covered |
|---|---|---|---|
| Local setup | 1-10 | Homebrew/Brewfile, uv, OrbStack, pre-commit, SOPS, MLX model servers, TEI embedder and reranker, LiteLLM gateway with budgets and fallbacks | Docker Desktop/Colima/Podman, Ollama/llama.cpp/vLLM, Portkey/Kong AI gateways |
| Storage and vectors | 11-15, 31 | pgvector (HNSW, halfvec), Qdrant, OpenSearch, S3 originals with versions and Object Lock, Valkey | Weaviate, Milvus, Pinecone, Elasticsearch, Azure AI Search, LanceDB |
| Ingestion | 31 | parsers (markdown, HTML, PDF, DOCX, CSV, text, Tika, Docling), normalisers, PII masking/pseudonymising, 6 chunkers (fixed, recursive, structure, semantic, sentence-window, parent-child), enrichers (context headers, contextual retrieval, questions, entities, project glossaries), embedders, manifest, queue, idempotent replace-not-append | Unstructured, LlamaParse, Azure Document Intelligence, late chunking, ColBERT/ColPali |
| Search and ranking | 32 | query transformers (rewrite, multi-query, HyDE, decompose, step-back, expand-terms, history), dense / keyword / hybrid retrieval, RRF / weighted / DBSF fusion, cross-encoder / LLM / TEI rerankers, MMR, dedupe, recency, parent and window expansion, per-document caps | SPLADE, ColBERT, Cohere/Voyage rerankers, learned fusion |
| Augmentation and LLM | 33 | context builders (budgets, lost-in-the-middle ordering), cited generation with registered prompts, extractive fallback, streaming, conversation memory, exact and semantic caches | Function calling, structured output, long-context instead of RAG |
| Architectures | 35 | naive, standard, corrective, self-reflective, adaptive, agentic, GraphRAG, SQL RAG: one slot | LangGraph/LlamaIndex agents, Microsoft GraphRAG global search, Neo4j |
| Evaluation | 26, 32-35, 37 | retrieval metrics, answer metrics (context recall, citations, abstention, groundedness, leaks), guard catch and false-alarm rates, CI gates, online evaluation per release | Ragas, DeepEval, TruLens, Phoenix, LLM-as-judge |
| Guardrails and safety | 34 | injection, context-injection, PII, secrets, topics, size, toxicity, groundedness, LLM judge, webhook; per stage; blocked messages | Llama Guard, NeMo Guardrails, Guardrails AI, cloud content filters |
| Security | 6, 16-18, 28, 29, 36, 37 | OIDC + JWT, OPA policies with pre-filter and post-check, access in every store, row-level security, OpenBao dynamic secrets, workload identities, admission policies, signed images | OpenFGA/SpiceDB, Cedar, cloud IAM, service mesh mTLS |
| Audit and observability | 19-23 | OpenTelemetry, Prometheus SLOs and alerts, Tempo and Loki, Langfuse with masking, a hash-chained audit log with anchors | Datadog, Honeycomb, Arize, Splunk |
| Governance and compliance | 24, 25, 36, 38 | prompt registry, model/dataset/system cards and lineage, risk register with evidence, framework mapping (NIST AI RMF, ISO/IEC 42001, EU AI Act, APPs), standards and doctor | GRC platforms, OWASP LLM Top 10, MITRE ATLAS |
| Data lifecycle | 36, 37 | access changes in place, retention with legal holds, erasure of every copy, blue/green re-index, backups with drills | CDC (Debezium), per-tenant databases |
| Delivery and production | 27, 29, 37 | CI gates, SBOM and signing, GitOps, staging/prod, canaries with analysis, promotion gates, HA Postgres with PITR, DR drills, cloud mapping | Flagger, feature flags, managed databases, multi-region |
| Reuse | 30, 38 | contracts and registry, SDK, packaged profiles, plugins, template, catalogue, versioning | Backstage templates, monorepo, platform-as-a-service |

### What this guide could not prove here

Everything above was built and its tests run, but some parts can only be fully proven in your environment. Plan
these in your first weeks:

- **Real models.** Tests use a hashing embedder, an extractive generator and scripted LLMs; gateway, TEI, LLM
  rerankers and transformers, agentic and SQL RAG, the LLM judge and the webhook guard were tested with stand-ins.
  Rerun every evaluation with your models and set thresholds from the results.
- **Real clusters.** Kubernetes manifests were checked by a real API server with the operators' schemas, but no
  controller ran: canaries, CloudNativePG failover, backups and the DR drill need a staging cluster. Compose and
  Kubernetes runs on a Mac weren't possible in the build environment.
- **Engines.** OpenSearch adapters were tested against a mock; pgvector's halfvec path needs pgvector 0.7+.
- **Law.** Framework mappings show where controls contribute, not compliance; EU AI Act timelines were under
  revision in mid-2026.

## Benefits

- Minutes to a correct project, not weeks to an approximate one.
- One engine, one set of standards, checked automatically in every project.
- Projects stay small: configuration, a few components, their questions and documents.
- Improvements reach everyone through versions and `copier update`.
- Reviews get faster: the platform's evidence is reused; only the project's specifics are new.

## Drawbacks and risks

- A platform is a product: it needs an owning team, a roadmap, support and documentation.
- Compatibility is a promise: a breaking change costs every project; keep 1.x stable and announce 2.0 early.
- Golden paths can become gilded cages: keep plugins and include overrides as escape hatches, and accept
  contributions.
- Template drift: projects that never run `copier update` fall behind; the doctor and the version pin make that
  visible.
- Standards can become box-ticking: keep "reviewed" items in the readiness review, not just the doctor.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| Cookiecutter | The classic project template tool | One-off generation is enough, updates aren't needed |
| Backstage software templates | A developer portal that runs templates and lists projects | You have, or want, an internal developer portal |
| Monorepo | All projects in one repository with the platform | Few teams, strong central ownership |
| Hosted RAG service | Projects send documents and questions to one shared service | Use cases are similar; teams shouldn't run anything |
| LlamaIndex / LangChain / Haystack as the base | General frameworks instead of rag-core | You prefer their ecosystem; keep the platform's gates around them |
| Managed RAG (Bedrock Knowledge Bases, Vertex AI Search, Azure AI Search) | The cloud runs ingestion and retrieval | Speed matters more than control; check access control and evaluation fit |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| A handful of internal assistants | Template + versioned rag-core (this step) |
| Dozens of teams | Same, run from a developer portal, with a platform team and inner-source contributions |
| Many near-identical knowledge bots | A hosted multi-tenant rag-api with per-tenant config, built on the same core |
| One regulated, high-risk system | Its own repository from the template, with extra reviewed controls and stricter thresholds |
| A quick prototype | The SDK and the offline profile in a notebook; move to the template before real data |

## Common mistakes

- Forking the platform for one project instead of adding a plugin or proposing a change.
- Copying `rag.yaml` instead of including the platform profiles: the copy never gets fixes.
- Templates without tests: a template that generates a failing project is worse than none.
- Treating the doctor as the whole review.
- Breaking changes in a MINOR version.
- Sample questions left in place of real ones.

## Done when

- [ ] `just new-project ../try-it` and then `just check` in it passes on the first run
- [ ] `just doctor` passes on the platform; `just catalogue --check` passes
- [ ] You've read `docs/standards/rag-standards.md` and agreed the "reviewed" items with security, privacy and
      operations
- [ ] rag-core 1.0.0 is published to your package index; the template pins it
- [ ] `just audit-test` passes
- [ ] ADR-0038 is committed

## Recap

> **RECAP**
> The platform is now something other teams can build on:
> - rag-core 1.0.0 with an SDK, packaged profiles and plugins
> - standards with ids, checked by `rag doctor`
> - a project template that passes every gate on its first run
> - a generated catalogue of all 94 components (Appendix C)
>
> And the guide is complete: 38 steps from an empty Mac to a production RAG platform with local development,
> switchable components for every stage, evaluation, guardrails, security, audit, governance, lifecycle, production
> delivery and a reuse kit. The coverage map above is your index; Appendix A has every file and command, Appendix B
> every term, Appendix C (`docs/catalogue.md`) every option.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `libs/rag-core/src/rag_core/sdk.py` | `RagApp`: one object to ingest, search, answer, stream, check and validate over the platform's pipelines |
| `libs/rag-core/src/rag_core/config.py` (changed) | `PACKAGED` and `read()`: `include:` of packaged or relative profile files, renamed `<name>/<profile>` |
| `libs/rag-core/src/rag_core/evaluate.py` (changed) | Evaluation variants read `rag.yaml` with its includes |
| `libs/rag-core/src/rag_core/profiles/platform.yaml` | rag-core's copy of the platform's `rag.yaml`, for `include: {platform: rag-core:platform.yaml}` |
| `libs/rag-core/src/rag_core/registry.py` (changed) | Plugins named in `RAG_PLUGINS`, failing loudly on a wrong name |
| `libs/rag-core/src/rag_core/__init__.py` (changed) | Exports `Container`, `register`, `ComponentError` and `__version__ = "1.0.0"` |
| `libs/rag-core/pyproject.toml` (changed), `uv.lock` | rag-core version 1.0.0 |
| `libs/rag-core/CHANGELOG.md` | rag-core's changelog: what 1.0.0 contains and what counts as breaking |
| `libs/rag-core/src/rag_core/doctor.py` | `rag doctor`: the automatable standards as rules with ids, levels and fixes |
| `libs/rag-core/src/rag_core/cli.py` (changed) | The `rag doctor [PATH] [--json]` command |
| `docs/standards/rag-standards.md` | The written standards: MUST / SHOULD / reviewed, with ids, checks and evidence; versioning |
| `libs/rag-core/tests/test_sdk.py` | SDK, includes, packaged profiles and plugins (6 tests) |
| `libs/rag-core/tests/test_doctor.py` | The doctor on the platform, an empty folder, missing questions, stand-ins, the CLI (5 tests) |
| `templates/rag-project/copier.yml` | The template's ten questions, validators and defaults |
| `templates/rag-project/template/…` | The generated project: rag.yaml, pyproject, components, evals, justfile, CI, tests, Dockerfile, deploy, card, risk acceptance, retention, ADR-0001, README, samples, answers file |
| `tests/test_template.py` | Three answer sets each generate a project that passes its gates; answers shape the project; bad names are refused (5 tests) |
| `scripts/catalogue.py` | Generates (or checks) `docs/catalogue.md` from the component registry |
| `docs/catalogue.md` | Appendix C: all 94 components in 24 kinds, with settings, defaults and test status |
| `justfile` (changed) | `new-project`, `doctor`, `catalogue`, `sync-profiles`; `ci-config` runs the doctor and the catalogue check |
| `docs/adr/0038-a-reuse-kit-for-rag-projects.md`, `docs/adr/README.md` | ADR-0038 and its index row |
| `docs/steps/step-38-reuse-kit-template-sdk-standards.md` | This write-up |

## Notes for this repository

- **System card brought up to date.** `cards/systems/rag-api.yaml` (Step 25) still described a search-only
  service. It now records what rag-api does after Steps 32-38 (cited answers or "I don't know", guards, the
  architecture slot), its additional inputs (`model:reranker`, `model:qwen-fast`, `model:qwen-quality`,
  `prompt:rag-answer`) and real known limitations (guard gaps, citations aren't correctness, cost of the
  heavier architectures); `docs/cards/` was regenerated with `just cards docs`.
- **Profile count.** This repository's `rag.yaml` has five profiles (Step 36 added `local-v2`), so `rag doctor`
  shows 22 results rather than the guide's 21. Everything passes.
- **Test totals.** The guide says 548 tests in total after this step; this repository's suite is larger because
  earlier steps added extra tests (731 passed and 151 skipped without the Postgres-backed suites here). The 16 new
  tests are exactly the guide's.
- **Template details the guide doesn't show in full.** The guide lists but doesn't print `README.md.jinja`,
  `.gitignore`, the sample documents, `src/{{module}}/__init__.py.jinja`, the answers-file template and
  `docs/adr/0001-build-on-the-rag-platform.md.jinja`; they were written to match the chapter (the samples contain
  exactly the facts the sample questions and tests need: "20 days of annual leave", carry-over, a doctor's
  certificate, WFH days, and a restricted bonus pool). The guide shows `kustomization.yaml.jinja` and
  `namespace.yaml.jinja` in one block; they are two files here.
- **Lint-clean output.** The generated project's `just check` starts with `just lint`, so the template's Python is
  written to pass `ruff check` and `ruff format --check` for any project name (a few long lines from the guide were
  split, and `rag_core` is imported as a third-party package in the project), the generated `pyproject.toml` sets
  the platform's ruff style, and `tests/test_template.py` also runs both ruff checks in each generated project.
- **Doctor fixes everywhere.** The guide's CFG-1 "can't be read" and CFG-5 "can't be read" results had no fix text;
  here they do, so "every failure carries a fix" holds for every path.
- **Copier version.** `tests/test_template.py` pins `copier==9.19.0` and runs it with `uvx` (verified here); Copier
  never enters `uv.lock`.
- **Not run here.** `uv sync` inside a generated project needs rag-core 1.0.0 on your package index (not published
  from this container); the template tests run the generated project with the platform's own environment instead.
  The generated CI workflow keeps the guide's `<sha>` placeholders, and the Dockerfile and kustomization keep
  `sha256:<digest>` placeholders, to be filled when the platform publishes a release.
