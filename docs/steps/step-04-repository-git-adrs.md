# Step 4 · Repository, git conventions and your first ADRs

*Step 4 of 38 · Phase A · Workstation*

## At a glance

| | |
|---|---|
| **Goal** | Turn `~/dev/rag-platform` into a properly organised git repository: a monorepo with a uv workspace, signed commits, a branching and commit-message convention, a private GitHub remote, and your first four ADRs recording the decisions from Steps 1–3. |
| **Time** | About 60–90 minutes. |
| **You'll end up with** | The folder structure every later step builds in, a working `just` command menu, a shared library you can import, and a written record of why the platform looks the way it does. |
| **New words** | Repository, commit, branch, remote, pull request, monorepo, workspace, Conventional Commits, signed commit, SSH key, ADR, supersede, `.gitignore`, trunk-based development. |

## The big idea

> **ANALOGY · A filing cabinet with a time machine and a decision diary**
> The **repository** is one filing cabinet holding the whole project, with a time machine built in: every
> **commit** is a save point with a note explaining what changed. You can return to any save point.
> A **branch** is a separate draft. You write your change there without touching the official copy (`main`). A
> **pull request** asks someone (or an automated checker) to review the draft before it's merged into the
> official copy.
> A **signed commit** carries a wax seal proving it really came from you.
> The **ADRs** are a decision diary: short notes recording *why* each big choice was made, so in six months
> nobody (including you) has to guess.

The code tells you **what** the system does; git history tells you **when and how** it changed; ADRs tell you
**why**. Enterprises need all three.

## What we're doing

1. Configure git with your identity and safe defaults.
2. Create an SSH key for logging in to GitHub and for signing commits.
3. Initialise the repository and create the folder skeleton.
4. Add the hygiene files: `.gitignore`, `.gitattributes`, `.editorconfig`, `README.md`, PR template, CODEOWNERS.
5. Turn the repo into a uv workspace and add the first shared library, `rag-common`.
6. Add a `justfile`: a menu of short commands.
7. Write the ADR template and ADR-0001 to ADR-0004.
8. Make your first Conventional Commits and check the signatures.
9. Push to a private GitHub repository and protect `main`.
10. Practise the full branch → pull request → squash merge cycle once.

## Why we're doing this

> **WHY THIS MATTERS**
> Everything after this step (services, configs, evaluation datasets, infrastructure) lives in this repository. If
> its structure, history and decision records are sloppy, every later step inherits the mess. If they're clean, an
> auditor, a new teammate or an interviewer can understand the whole platform in minutes.

| Need | How this step meets it |
|---|---|
| **Traceability:** who changed what, when and why | Git history with clear commit messages, linked to ADRs |
| **Integrity:** proof that changes weren't forged | Signed commits, verified by GitHub |
| **Safe change:** nothing reaches `main` unchecked | Branches + pull requests + branch protection (and CI checks from Step 27) |
| **One version of everything** | A monorepo with a single uv lockfile shared by all Python services |
| **Decision memory** | ADRs: decisions survive staff turnover and your own forgetfulness |
| **Consistency** | `.editorconfig`, `.gitattributes` and a `justfile` make everyone's environment behave the same |

> **IN A COMPANY**
> Regulated organisations (banks, health, government) must show **change control**: every production change is
> traceable to a reviewed, approved request made by an identified person. Signed commits + protected branches +
> pull requests + ADRs is the standard way engineering teams provide that evidence. Frameworks such as SOC 2,
> ISO 27001 and ISO/IEC 42001 all ask for it in one form or another.

## Key ideas

### Monorepo vs polyrepo

| | Monorepo (our choice) | Polyrepo |
|---|---|---|
| **What it is** | One repository holding all services, libraries, infra and docs | One repository per service or library |
| **Changing a shared library** | One pull request updates the library and every service that uses it | Publish a new library version, then update each repo separately |
| **Dependency versions** | One lockfile, so every service uses the same version | Each repo drifts on its own |
| **Access control** | Coarser: everyone sees everything (CODEOWNERS adds review rules) | Fine-grained per repo |
| **Best for** | One team or a platform where pieces change together | Many independent teams with separate release cycles |

> **IN PLAIN ENGLISH**
> Your platform's pieces are tightly connected: the gateway, the ingestion service and the API all share code for
> logging, auth and tracing. Keeping them in one cabinet means one change can update everything consistently.
> That's why we pick a monorepo.

**Figure 11 · The repository layout.** Each top-level folder has one job; services import shared code from `libs/`.

```text
rag-platform/          the repository root · also the uv workspace root
│                      pyproject.toml · uv.lock · justfile · README.md · .gitignore · .gitattributes · .editorconfig
├── libs/              Shared code, imported by services (rag-common; later: auth, tracing…)
├── services/          Things that run: API, ingestion, workers (from Step 9 onwards)   ← services import libs
├── infra/             How it runs: compose/ k8s/ config/ (Steps 11, 29)
├── evals/             How good it is: golden datasets, eval runs (Step 26)
├── docs/adr/          Why it is this way: Architecture Decision Records (this step)
├── bootstrap/         Machine setup: Brewfile, notes (Steps 1–3)
├── tests/             Cross-service tests: integration and end-to-end tests
└── .github/           Collaboration rules: PR template, CODEOWNERS, CI (Step 27)
```

### uv workspaces

A **workspace** is uv's way of managing several Python packages in one repository. All members share **one
`uv.lock`** and **one `.venv`** at the root, so they can never disagree about versions. The root `pyproject.toml`
lists which folders are members.

### Branching: trunk-based development

**Figure 12 · Trunk-based development.** `main` stays releasable; each change happens on a short-lived branch and
comes back through a pull request as one squashed commit.

```text
main ──●──────────────────────────────●──────▶   always working · protected · only changed through PRs
        \                            ↑
         \ branch off                │ squash merge
          ●──●──●  feat/step-05-precommit ── Pull request: automated checks (Step 27) + review
          signed commits; short-lived branch: hours to a few days, one focused change
```

- `main` is the **trunk**: always working, never edited directly.
- Each change gets a short-lived branch named after what it does, e.g. `feat/step-05-precommit`,
  `fix/gateway-timeout`, `docs/adr-0005`.
- The branch returns through a **pull request (PR)** and is **squash-merged**: all its small commits become one
  clean commit on `main`.

### Conventional Commits

A shared format for commit messages, so history is readable by people *and* tools (for changelogs and version
numbers).

**Figure 13 · Anatomy of a Conventional Commit message.**

```text
feat(gateway)!: add fallback model for timeouts
│    │       │  └─ description: short, imperative, lower case
│    │       └──── ! = breaking change
│    └──────────── scope: which area (optional)
└───────────────── type: what kind of change
```

| Type | Use it for |
|---|---|
| `feat` | A new capability |
| `fix` | A bug fix |
| `docs` | Documentation only (including ADRs) |
| `refactor` | Restructuring without changing behaviour |
| `test` | Adding or fixing tests |
| `build` | Dependencies, Brewfile, lockfile, packaging |
| `ci` | CI pipeline changes |
| `chore` | Housekeeping that fits nowhere else |

A `!` after the type/scope, or a `BREAKING CHANGE:` line in the body, marks a change that breaks existing users.
That convention is what drives **Semantic Versioning**: breaking change → major version, `feat` → minor version,
`fix` → patch version. Step 5 adds a hook that rejects messages not in this format.

### Architecture Decision Records (ADRs)

An **ADR** is a short Markdown file recording one significant decision: the **context** (the situation and
constraints), the **decision**, the **alternatives considered**, and the **consequences** (what gets easier,
what gets harder, what risks we accept). The format was popularised by Michael Nygard in 2011.

**Figure 14 · The ADR lifecycle.**

```text
Proposed ──▶ Accepted ──▶ Superseded by ADR-00xx (newer)
(written,    (the decision  └─▶ Deprecated (no longer applies)
 open for     in force)
 comment) ──▶ Rejected (kept, so nobody re-asks)
```

An accepted ADR is **never rewritten**. To change your mind, write a NEW ADR that **supersedes** it, so the
history of reasoning survives.

> **WHAT COUNTS AS 'SIGNIFICANT'?**
> Write an ADR when a decision is hard or expensive to reverse, affects more than one component, or someone will
> one day ask "why did we do it this way?" Choosing a database: yes. Naming a variable: no.

### Other terms

| Term | Plain-English meaning |
|---|---|
| **Remote / origin** | A copy of the repository on a server (GitHub). `origin` is the default nickname for it. |
| **Push / pull** | Send your commits to the remote / fetch other people's commits from it |
| **SSH key** | A pair of matching files: a private key that stays secret on your Mac, and a public key you give to GitHub. Used to prove it's you without a password. |
| **`.gitignore`** | A "do not pack" list: files git must never track (secrets, `.venv`, model files) |
| **`.gitattributes`** | Rules for how git treats file types (line endings, binary files) |
| **EditorConfig** | A small file telling every editor the same formatting basics (indentation, line endings) |
| **CODEOWNERS** | A GitHub file naming who must review changes to which folders |
| **Branch protection / rulesets** | GitHub settings that block direct pushes to `main` and require PRs, checks and signatures |

## How to do it

All commands run in the macOS Terminal. `~/dev/rag-platform/` is the root of this repository.

### 1 · Configure git

Use the same email address as your GitHub account, or GitHub's private **noreply** address (GitHub → Settings →
Emails → "Keep my email addresses private" shows it, e.g. `12345678+yourname@users.noreply.github.com`). The
noreply address stops your personal email appearing in commit history.

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"   # or your GitHub noreply address
git config --global init.defaultBranch main          # new repos start on "main"
git config --global pull.ff only                     # never create surprise merge commits on pull
git config --global fetch.prune true                 # forget branches deleted on the server
git config --global core.autocrlf input              # store LF line endings (Linux-style) in the repo
git config --global --list | grep -E 'user|init|pull|fetch|autocrlf'
```

### 2 · Create an SSH key for GitHub login and commit signing

One modern key (**ed25519**) does both jobs. Set a passphrase when asked; macOS Keychain will remember it.

```bash
ssh-keygen -t ed25519 -C "you@example.com" -f ~/.ssh/id_ed25519
ssh-add --apple-use-keychain ~/.ssh/id_ed25519      # store the passphrase in Keychain
```

`~/.ssh/config` (reference copy: [`bootstrap/home/.ssh/config`](../../bootstrap/home/.ssh/config)):

```text
Host github.com
  AddKeysToAgent yes
  UseKeychain yes
  IdentityFile ~/.ssh/id_ed25519
```

Log in to GitHub with `gh` and upload the public key **twice**: once for authentication (pushing code) and once
for signing (verifying commits).

```bash
gh auth login --git-protocol ssh --web                                   # follow the browser prompts
gh auth refresh -h github.com -s admin:public_key,admin:ssh_signing_key  # permission to add keys
gh ssh-key add ~/.ssh/id_ed25519.pub --title "M5 Max" --type authentication
gh ssh-key add ~/.ssh/id_ed25519.pub --title "M5 Max signing" --type signing
ssh -T git@github.com              # expect: "Hi <username>! You've successfully authenticated…"
```

Turn on commit signing, and tell git which keys it should trust when verifying signatures locally:

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
git config --global tag.gpgsign true
echo "$(git config --global user.email) namespaces=\"git\" $(cat ~/.ssh/id_ed25519.pub)" >> ~/.ssh/allowed_signers
git config --global gpg.ssh.allowedSignersFile ~/.ssh/allowed_signers
```

Parts 1 and 2 are also scripted, idempotently, in [`bootstrap/git-setup.sh`](../../bootstrap/git-setup.sh):

```bash
GIT_NAME="Your Name" GIT_EMAIL="12345678+you@users.noreply.github.com" bash bootstrap/git-setup.sh
CHECK_ONLY=1 bash bootstrap/git-setup.sh     # just show the current state
```

The resulting `~/.gitconfig` is shown in [`bootstrap/home/.gitconfig`](../../bootstrap/home/.gitconfig), and the
format of `~/.ssh/allowed_signers` in
[`bootstrap/home/.ssh/allowed_signers.example`](../../bootstrap/home/.ssh/allowed_signers.example).

> **IN PLAIN ENGLISH**
> The private key never leaves your Mac. Git uses it to stamp each commit with a signature. GitHub (and your own
> Mac, via `allowed_signers`) use the public key to check the stamp. If anyone forges a commit in your name, it
> shows as **Unverified**.

> **WATCH OUT**
> Never copy, email or commit `~/.ssh/id_ed25519` (no `.pub` at the end). That's the private key. Only files ending
> in `.pub` are safe to share.

### 3 · Initialise the repository and create the skeleton

```bash
cd ~/dev/rag-platform
git init
mkdir -p docs/adr docs/architecture docs/runbooks libs services infra/compose infra/k8s infra/config \
         evals tests scripts .github
for d in docs/architecture docs/runbooks services infra/compose infra/k8s infra/config evals tests scripts; do
  touch "$d/.gitkeep"     # git doesn't track empty folders; an empty .gitkeep file keeps them
done
tree -a -I '.git' -L 2
```

### 4 · Add the hygiene files

- [`.gitignore`](../../.gitignore): Python build/cache folders; **secrets** (`.env`, `.env.*` except
  `.env.example`, `*.pem`, `*.key`; Step 6 handles these properly); **data and models**, far too big for git and
  possibly sensitive (`data/`, `models/`, `*.gguf`, `*.safetensors`, `*.bin`, `*.parquet`); and OS/editor clutter
  (`.DS_Store`, `.idea/`, `.vscode/*` except `extensions.json`, `.direnv/`).
- [`.gitattributes`](../../.gitattributes): normalise all text files to LF line endings (`* text=auto eol=lf`);
  treat `*.png *.jpg *.pdf *.gguf *.safetensors` as binary (never diff or change line endings); mark `uv.lock` as
  `linguist-generated=true` so GitHub collapses it in diffs.
- [`.editorconfig`](../../.editorconfig): UTF-8, LF, final newline, trim trailing whitespace, 4-space indents;
  2 spaces for YAML/JSON/TOML; for Markdown, 2 spaces and *keep* trailing whitespace (two trailing spaces = a line
  break in Markdown).
- [`README.md`](../../README.md): one-line description, the three Quick-start commands (`just bootstrap`,
  `just sync`, `just check`), the layout, and a link to the ADR index.
- [`.github/pull_request_template.md`](../../.github/pull_request_template.md): "What and why", "How was it
  tested?", and a checklist (Conventional Commits, ADR added/updated, docs updated, no secrets/data/models).
- [`.github/CODEOWNERS`](../../.github/CODEOWNERS): `*  @your-github-username`. Every change needs review from
  the owner; teams would list different owners per folder, e.g. `/infra/ @platform-team`,
  `/evals/ @ml-quality-team`.

### 5 · Make the repository a uv workspace and add the first library

[`pyproject.toml`](../../pyproject.toml) at the root:

```toml
[project]
name = "rag-platform"
version = "0.1.0"
description = "Workspace root for the RAG platform"
requires-python = ">=3.12,<3.13"   # pinned to 3.12, see ADR-0003
dependencies = []

[dependency-groups]
dev = []                           # shared dev tools (ruff, pytest…) arrive in Step 5

[tool.uv]
package = false                    # the root is a container for members, not a package itself

[tool.uv.workspace]
members = ["libs/*"]               # add "services/*" when the first service exists (Step 9)
```

```bash
cd ~/dev/rag-platform
echo "3.12" > .python-version              # one interpreter version for the whole repo
uv init --lib libs/rag-common              # creates a library using the "src layout"
rm -f libs/rag-common/.python-version      # if uv created one: the root file rules
uv lock
uv sync --all-packages                     # one .venv at the root, with every member installed
uv run --package rag-common python -c "import rag_common; print(rag_common.hello())"
# prints uv's template greeting, e.g. "Hello from rag-common!"
```

> **WHY `libs/*` ONLY FOR NOW?**
> Every folder matched by a `members` pattern must contain a `pyproject.toml`. `services/` only holds a `.gitkeep`
> placeholder today, so including it would make uv complain. You'll add `"services/*"` in the same commit that
> creates the first service.

> **WHAT IS THE 'SRC LAYOUT'?**
> The code lives in `libs/rag-common/src/rag_common/` rather than directly under `libs/rag-common/`. That stops
> Python from accidentally importing your uninstalled source folder during tests, so tests always exercise the
> package as it's really installed.

### 6 · Add a `justfile`: the project's command menu

[`justfile`](../../justfile) recipes:

| Recipe | Runs | Purpose |
|---|---|---|
| `just` (`default`) | `just --list` | List the recipes |
| `just bootstrap` | `brew bundle --file=bootstrap/Brewfile` | Install system tools from the Brewfile |
| `just sync` | `uv sync --all-packages` | Install Python packages for every workspace member |
| `just lock` | `uv lock` | Re-resolve the lockfile after editing a `pyproject.toml` |
| `just check` | `brew bundle check --file=bootstrap/Brewfile` then `uv sync --locked --all-packages` | Fail if tools or the lockfile are out of date (CI will run this too) |
| `just adr "Title"` | a small bash script | Create the next numbered ADR from the template |

The `adr` recipe finds the highest `NNNN-` number in `docs/adr`, adds one, turns the title into a lower-case
slug (`Use Qdrant for vectors` → `use-qdrant-for-vectors`), and copies `0000-template.md` replacing `NNNN`,
`TITLE` and `YYYY-MM-DD` (today).

```bash
just            # lists the recipes
just check      # both checks should pass
```

> **IN PLAIN ENGLISH**
> A `justfile` is a menu of named shortcuts. Instead of remembering `uv sync --locked --all-packages`, anyone types
> `just check`. The same names will work in CI (Step 27), so local and automated checks are identical.

### 7 · Write the ADR template and the first four ADRs

- [`docs/adr/0000-template.md`](../adr/0000-template.md): Status (Proposed | Accepted | Rejected | Deprecated |
  Superseded by ADR-XXXX), Date, Deciders; then **Context**, **Decision** ("We will …"), **Alternatives
  considered** (Option | Pros | Cons | Why not chosen), **Consequences**, **Revisit when**.
- [ADR-0001 · Record architecture decisions](../adr/0001-record-architecture-decisions.md): every significant
  decision becomes a numbered, immutable Markdown ADR; changes come through superseding ADRs. Rejected: wiki
  pages (drift from code, not reviewed in PRs), long design docs only (too heavy for small decisions), no records.
- [ADR-0002 · Workstation tools via Homebrew + Brewfile](../adr/0002-workstation-tools-via-homebrew-brewfile.md):
  every tool declared, with a comment, in `bootstrap/Brewfile`; analytics off. Rejected: Nix (overkill), Dev
  Containers (no Metal GPU), manual installs (not reproducible).
- [ADR-0003 · Python 3.12 managed by uv, committed lockfile](../adr/0003-python-312-managed-by-uv.md): uv for
  interpreters, environments and locking; Python `>=3.12,<3.13`; one workspace, one committed `uv.lock`;
  only-managed interpreters. Rejected: Poetry, pip + pip-tools, conda/pixi, Python 3.13+.
- [ADR-0004 · Native models, containerised services (OrbStack)](../adr/0004-orbstack-native-models-containerised-services.md):
  model servers native on macOS (Metal), every other service in OrbStack containers, via `host.docker.internal`;
  VM capped at 24 GB / 8 CPUs; ports on 127.0.0.1; named volumes; log rotation 10 MB × 3. Rejected: Docker Desktop,
  Colima (kept as fallback), Podman, models in containers.
- [`docs/adr/README.md`](../adr/README.md): the ADR index. New ADR: `just adr "Short title"`, then fill it in and
  add a row here.

Test the `adr` recipe, then remove the test file:

```bash
just adr "Test entry"          # created docs/adr/0005-test-entry.md
rm docs/adr/0005-test-entry.md
```

Your Step 3 notes are now captured in ADR-0004. Delete `bootstrap/NOTES-step3.md`, or keep it as a scratch file.

### 8 · First commits, and check the signatures

Commit in logical slices, so each commit tells one story:

```bash
git add .gitignore .gitattributes .editorconfig README.md .github justfile
git commit -m "chore: initialise repository hygiene and command menu"

git add bootstrap
git commit -m "build(bootstrap): add Brewfile for workstation tools (steps 1-3)"

git add pyproject.toml .python-version uv.lock libs
git commit -m "build: create uv workspace with rag-common library"

git add docs
git commit -m "docs(adr): record ADR-0001 to ADR-0004"

git add -A && git status        # anything left? (placeholders, notes) commit it with a clear message
git log --oneline
git log --show-signature -1     # expect: Good "git" signature for you@example.com
```

> **CHECK BEFORE EVERY COMMIT**
> Run `git status` and read the list. If you ever see `.env`, a `models/` file or anything secret staged, stop and
> fix `.gitignore`. Removing a secret from git history later is painful, and the secret must be considered leaked
> anyway.

### 9 · Push to a private GitHub repository and protect `main`

```bash
gh repo create rag-platform --private --source=. --remote=origin --push
gh repo view --web              # opens the repo in your browser
```

On GitHub, each commit should show a green **Verified** badge.

Now protect `main`: **Settings → Rules → Rulesets → New branch ruleset**, target the default branch, and enable:

- Restrict deletions and Block force pushes
- Require a pull request before merging (approvals: 0 while you work alone)
- Require signed commits
- (Step 27 will add) Require status checks to pass

> **PLAN LIMITS**
> GitHub enforces rulesets and branch protection on private repositories only on paid plans (Pro, Team,
> Enterprise). On the Free plan, they work on public repositories. If your repo is private on Free, follow the same
> discipline by hand: never push to `main` directly, and always go through a PR.

### 10 · Practise the pull-request cycle once

```bash
git switch -c docs/readme-adr-link                       # new short-lived branch
echo "" >> README.md && echo "Decision log: 4 ADRs accepted." >> README.md
git commit -am "docs: note ADR count in README"
git push -u origin docs/readme-adr-link
gh pr create --fill                                      # opens a PR using the template
gh pr merge --squash --delete-branch                     # squash-merge and tidy up
git switch main && git pull                              # main now has the change as one commit
```

## Benefits

- **A full audit trail:** every change is signed, attributed, described in a standard format and (via PRs)
  reviewed.
- **Decision memory:** ADRs answer "why?" without anyone needing to remember, and give interviewers and auditors a
  guided tour.
- **One version of everything:** a single lockfile and workspace keep all Python code consistent.
- **One-word commands:** the `justfile` makes setup, checking and ADR creation repeatable, and CI will reuse it.
- **Protection by default:** `.gitignore` blocks secrets, data and models before they can be committed.

## Drawbacks and risks

- **Monorepos grow.** Clone time, CI time and noise increase over time. Large organisations need specialist
  tooling (Bazel, Pants, Nx) to stay fast.
- **Coarse access control.** Everyone with access sees everything. CODEOWNERS controls review, not visibility.
- **Process overhead.** PRs and ADRs take time. For a solo project, keep ADRs short and approvals at zero.
- **Signing keys are a responsibility.** A stolen private key can sign commits as you. Protect it with a
  passphrase, and revoke it on GitHub if it's ever exposed.
- **Squash merges lose the detailed branch history.** Usually fine; teams that need every intermediate step use
  rebase-merge instead.
- **Hosted on GitHub.** Your code lives on a third-party service. Enterprises often self-host (GitLab, GitHub
  Enterprise Server) for data-residency reasons.

## Alternatives

| Choice | Alternatives | Choose the alternative when |
|---|---|---|
| Monorepo | Polyrepo; monorepo build tools (Bazel, Pants, Nx, Turborepo) | Independent teams and release cycles (polyrepo); very large monorepos needing incremental builds (build tools) |
| uv workspace | Separate projects each with their own lockfile | Services genuinely need conflicting dependency versions |
| Trunk-based development | GitHub Flow (very similar); GitFlow (develop + release branches); release branches | GitFlow suits software shipped in versioned releases to customers; trunk-based suits continuously deployed services |
| Conventional Commits | Free-form messages; Gitmoji; ticket-prefixed messages (`ABC-123: …`) | Company already mandates ticket IDs; combine them: `fix(api): handle empty query (ABC-123)` |
| SSH commit signing | GPG signing; gitsign (Sigstore, keyless, short-lived certificates) | GPG for older tooling; gitsign for supply-chain-focused orgs that don't want long-lived keys |
| Nygard-style ADRs | MADR (more structured template); Y-statements (one sentence); RFCs/design docs; Confluence decision pages | MADR for teams wanting consistency; RFCs for large cross-team designs (often plus an ADR for the final decision) |
| ADR tooling: plain files + `just adr` | adr-tools, log4brains (publishes ADRs as a website) | You want a browsable ADR site for many teams |
| GitHub | GitLab (cloud or self-hosted), Gitea/Forgejo (self-hosted, light), Bitbucket, Azure DevOps | Data residency, air-gapped networks or existing company standards |
| Large files out of git | Git LFS; DVC; object storage (SeaweedFS S3, Step 14) with references in git | You must version models or datasets alongside code (DVC or LFS); otherwise keep them in object storage |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Solo learner or one small team building a platform | Monorepo + uv workspace + trunk-based + ADRs (this step) |
| Many teams, independent services, separate release schedules | Polyrepo, with shared libraries published to an internal package index |
| Huge monorepo (hundreds of engineers) | Monorepo plus Bazel/Pants for incremental builds and tests |
| Software shipped as numbered releases to customers | Release branches or GitFlow, with Conventional Commits driving changelogs |
| Regulated environment (finance, health, government) | Signed commits (often gitsign or a hardware key), protected branches, mandatory reviews, ADRs linked to change tickets, self-hosted git |
| Versioning ML models and datasets | DVC or object storage with metadata, never plain git |

## Common mistakes

- **Committing secrets**, e.g. a `.env` file, because `.gitignore` was added after the first commit. Create
  `.gitignore` first. If a secret is ever committed, **rotate it**: deleting it from history isn't enough.
- **Committing model weights or datasets.** Git slows to a crawl, and GitHub rejects files over 100 MB.
- **Editing an accepted ADR** to reflect a new decision. Write a new ADR that supersedes it instead.
- **Writing ADRs for trivia, or never writing them for big decisions.** Use the "hard to reverse / affects many
  parts / someone will ask why" test.
- **Long-lived branches** that drift for weeks and become painful to merge. Merge small changes often.
- **Vague commit messages** ("update", "fix stuff"). Say what changed and why, in Conventional Commits format.
- **Using a different email in git than on GitHub**, so commits show as Unverified, or aren't linked to your
  account.
- **Sharing the private SSH key** instead of the `.pub` file.

## Done when

- [ ] `git config --global --list` shows your name, email, `init.defaultbranch=main` and `commit.gpgsign=true`
- [ ] `ssh -T git@github.com` greets you by username
- [ ] The folder skeleton exists, and `tree -L 2` matches the layout diagram
- [ ] `.gitignore`, `.gitattributes`, `.editorconfig`, `README.md`, PR template and CODEOWNERS are committed
- [ ] `uv run --package rag-common python -c "import rag_common; print(rag_common.hello())"` works
- [ ] `just check` passes
- [ ] ADR-0001 to ADR-0004 and the ADR index are committed, and `just adr` creates a correctly numbered file
- [ ] `git log --show-signature -1` shows a Good signature, and GitHub shows Verified
- [ ] The private GitHub repo exists, with a ruleset on `main` (or, on the Free plan, the manual discipline)
- [ ] You completed one branch → PR → squash-merge cycle

## Recap

> **RECAP**
> `rag-platform` is now a real, signed, version-controlled monorepo: one uv workspace and lockfile, a clear folder
> for every concern, hygiene files that keep secrets and models out, a `just` menu, a private GitHub remote with a
> protected `main`, and a decision diary (ADR-0001 to ADR-0004) recording why Steps 1–3 were done the way they
> were. From now on, every change follows the same path: **branch → Conventional Commit → PR → squash merge**,
> and every significant decision gets an ADR.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| [`.gitignore`](../../.gitignore) | "Do not pack" list: Python caches/builds, secrets (`.env`, keys), data and model files, OS/editor clutter. |
| [`.gitattributes`](../../.gitattributes) | LF line endings for text, binary handling for images/PDFs/model files, `uv.lock` collapsed in GitHub diffs. |
| [`.editorconfig`](../../.editorconfig) | Same indentation, charset and line endings in every editor. |
| [`README.md`](../../README.md) | The guide's project README (quick start, layout, decisions), plus links to the step write-ups and source PDFs. |
| [`.github/pull_request_template.md`](../../.github/pull_request_template.md) | The checklist every pull request opens with. |
| [`.github/CODEOWNERS`](../../.github/CODEOWNERS) | Who must review changes (the repository owner, for every path). |
| [`pyproject.toml`](../../pyproject.toml) | uv workspace root: Python `>=3.12,<3.13`, empty `dev` group, members `libs/*`. |
| [`.python-version`](../../.python-version) | `3.12`: one interpreter version for the whole repo. |
| [`uv.lock`](../../uv.lock) | The single committed lockfile for every workspace member. |
| [`libs/rag-common/`](../../libs/rag-common/) | First shared library (src layout, `uv_build` backend) with uv's template `hello()`. |
| [`justfile`](../../justfile) | The command menu: `bootstrap`, `sync`, `lock`, `check`, `adr`. |
| [`docs/adr/0000-template.md`](../adr/0000-template.md) | The ADR template used by `just adr`. |
| [`docs/adr/0001-…0004-*.md`](../adr/README.md) | ADR-0001 to ADR-0004: ADRs themselves, Homebrew/Brewfile, Python 3.12 + uv, native models + OrbStack. |
| [`docs/adr/README.md`](../adr/README.md) | The ADR index. |
| `docs/architecture/`, `docs/runbooks/`, `services/`, `infra/{compose,k8s,config}/`, `evals/`, `tests/`, `scripts/` | Empty skeleton folders, kept in git with `.gitkeep`. |
| [`bootstrap/git-setup.sh`](../../bootstrap/git-setup.sh) | Scripted, repeatable version of parts 1–2 (git identity/defaults, ed25519 key, GitHub key upload, SSH signing). |
| [`bootstrap/home/.gitconfig`](../../bootstrap/home/.gitconfig) | Reference copy of the `~/.gitconfig` those commands produce (placeholder name/email). |
| [`bootstrap/home/.ssh/config`](../../bootstrap/home/.ssh/config) | Reference copy of `~/.ssh/config` for GitHub. |
| [`bootstrap/home/.ssh/allowed_signers.example`](../../bootstrap/home/.ssh/allowed_signers.example) | Example of `~/.ssh/allowed_signers` with a dummy key and the command that builds the real one. |
| [`docs/steps/step-04-repository-git-adrs.md`](step-04-repository-git-adrs.md) | This write-up. |
| [`docs/steps/README.md`](README.md), [`docs/glossary.md`](../glossary.md), [`CHANGELOG.md`](../../CHANGELOG.md) | Step 4 row, terms and entry added. |

## Notes for this repository

- **Repository already existed.** The repo was created on GitHub before this step, so `git init`,
  `gh repo create` (part 9), the ruleset (part 9) and the practice PR (part 10) are owner actions on GitHub, not
  files. The guide's four "logical slice" commits (part 8) are replaced by this repository's one-commit-per-step
  convention; the Brewfile was already committed in Steps 1–3.
- **Files outside the repo** (`~/.gitconfig`, `~/.ssh/config`, `~/.ssh/allowed_signers`) are stored as reference
  copies under `bootstrap/home/` and are copied to `~` during workstation setup (or written by
  `bootstrap/git-setup.sh`). No SSH key, private or public, is committed; `allowed_signers.example` holds a dummy
  key. Commit signing is configured only in those reference copies and the script, not in this repository's own
  git config.
- **`bootstrap/git-setup.sh`** is an addition of this repository that scripts the chapter's own commands. It is
  idempotent (doesn't overwrite an existing key, doesn't duplicate the `allowed_signers` line) and supports
  `SKIP_GITHUB=1` and `CHECK_ONLY=1`.
- **CODEOWNERS** uses the repository owner's handle `@deivamanikailasam` in place of the guide's
  `@your-github-username`; ADR "Deciders" likewise name the owner instead of `<you>`.
- **`.editorconfig`**: the guide puts the "two trailing spaces" comment at the end of the
  `trim_trailing_whitespace = false` line. The EditorConfig spec only recognises comments on their own line (an
  inline comment can become part of the value), so the comment was moved to the line above.
- **`justfile` / `README.md` indentation** was rebuilt from the PDF (recipes indented with 4 spaces; the README
  quick-start commands as an indented code block). The `adr` recipe's `sed` line, wrapped in the PDF, is one line.
- **`rag-common`** is exactly what `uv init --lib` (uv 0.11) generates (`uv_build` backend, `py.typed`, `hello()`),
  with a real description and README instead of uv's "Add your description here" placeholder.
- **`bootstrap/NOTES-step3.md` is kept** as the scratch file the guide allows; ADR-0004 is now the authoritative
  record of those decisions.
- **Validation done here** (Linux container, no macOS/Homebrew): `uv lock`, `uv sync --all-packages` and
  `uv sync --locked --all-packages` succeed with CPython 3.12; the `rag_common.hello()` check prints
  `Hello from rag-common!`; with `just` installed, `just` lists the recipes and `just adr "Test entry"` created
  `docs/adr/0005-test-entry.md` with the right number, title and date (then removed). `just check`'s first line
  needs Homebrew and was not run. `bootstrap/git-setup.sh` passes `bash -n` and was run twice against a throwaway
  `HOME` with a dummy key and `SKIP_GITHUB=1`, producing the expected `~/.gitconfig` and a single
  `allowed_signers` line.
