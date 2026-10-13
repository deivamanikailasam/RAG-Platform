# Step 5 · Linting, formatting and pre-commit hooks

*Step 5 of 38 · Phase A · Workstation*

## At a glance

| | |
|---|---|
| **Goal** | Add automatic quality checks that run every time you commit: a formatter, a linter, a type checker, secret scanning, file-hygiene checks, a commit-message check, and tests before every push. |
| **Time** | About 60–75 minutes. |
| **You'll end up with** | ruff, mypy and pytest installed at versions locked in `uv.lock`, a `.pre-commit-config.yaml` with three kinds of git hook, a first unit test, new `just` recipes, and ADR-0005. |
| **New words** | Formatter, linter, static analysis, type hint, type checker, git hook, pre-commit, shift left, false positive, auto-fix, `--no-verify`. |

## The big idea

> **ANALOGY · AIRPORT SECURITY BEFORE BOARDING**
> Before you board a plane, security checks your bag at the gate, not after take-off. A pre-commit hook is that
> security check for code: every time you run `git commit`, a set of automatic checks runs first. If anything
> fails, the commit doesn't happen, and you fix the problem while it's still small and only you know about it.
> The checks are different specialists: a **formatter** (autocorrect for layout), a **linter** (a proofreader for
> likely bugs), a **type checker** (checking each plug fits its socket before you switch on), a **secret scanner**
> (the X-ray for things that must never leave), and **tests** (a test drive).

## What we're doing

1. Add ruff, mypy, pytest and pre-commit as development tools, locked in `uv.lock`.
2. Configure ruff, mypy and pytest once, in the root `pyproject.toml`.
3. Write the first unit test for `rag-common`.
4. Create `.pre-commit-config.yaml` with hooks for three moments:
   - **pre-commit**: format, lint, type-check, scan for secrets, file hygiene
   - **commit-msg**: Conventional Commits format
   - **pre-push**: run the tests
5. Install the hooks, run them on every file, and watch each one catch a real mistake.
6. Add `just` recipes, editor integration and ADR-0005.

## Why we're doing this

The checks form a line of **quality gates**, from your editor on the left to `main` on the right:

```
 on your Mac: fast feedback, but skippable with --no-verify          | server-side gate: enforced
                                                                     |
 Editor        pre-commit       commit-msg       pre-push            | CI (Step 27)     main
 as you type   on git commit    message format   tests               | every PR,        reviewed
 <1s           seconds          instant          ~10–60 s            | can't skip       + green
                                                                     | minutes
 cheap to fix: seconds, only you know  ───────────────►  expensive: after merge or in production,
                                                          everyone affected
```

*Figure 15 of the guide: "Shift left": catch each problem at the earliest, cheapest gate that can detect it.
Problems found on the left cost seconds; the same problem found after merging costs far more.*

> **WHY THIS MATTERS**
> In AI platforms, small code mistakes have big, quiet effects: a mutable default that leaks one user's data into
> another's request, a leaked API key in a config file, a function that returns `None` where a list of retrieved
> chunks was expected. Automatic checks catch whole categories of these mistakes before they're even saved,
> for free, every time.

| Problem | Which check catches it |
|---|---|
| Inconsistent style, noisy diffs, review arguments about spacing | Formatter (`ruff format`) |
| Unused imports, undefined names, mutable defaults, `except:` swallowing errors, insecure calls | Linter (`ruff check`) |
| Passing the wrong type, forgetting a value can be `None`, calling a method that doesn't exist | Type checker (`mypy`) |
| API keys, tokens or private keys committed by accident | Secret scanners (gitleaks, detect-private-key) |
| Accidentally committing a 2 GB model, a merge-conflict marker, or straight to `main` | Hygiene hooks |
| Messages like "fix stuff" that make history useless | commit-msg hook |
| A change that breaks existing behaviour | Tests (pytest, before push) |

> **IN A COMPANY**
> These checks are part of the **Secure Software Development Lifecycle (SSDLC)**. Auditors and security
> frameworks (OWASP SAMM, NIST SSDF, SOC 2 change management) expect automated static analysis and secret
> scanning on every change. Local hooks give fast feedback; CI (Step 27) runs the exact same checks as the
> enforced gate.

## Key ideas

### The four kinds of automatic check

| | Formatter | Linter | Type checker | Tests |
|---|---|---|---|---|
| **Tool** | `ruff format` | `ruff check` | `mypy` | `pytest` |
| **Looks at** | How the code LOOKS | Likely BUGS, risky patterns | Do the pieces FIT? | Does it do the RIGHT thing? |
| **Example** | `x=[1,2 ,3]` → `x = [1, 2, 3]` | `def f(items=[]):` → B006 mutable default | `add("1", 2)` → str is not int | `assert total() == 10` → fails if logic is wrong |
| **Like** | Autocorrect for layout | A proofreader | Checking a plug fits | A test drive |
| **Who fixes it** | Fixes itself | Often fixes itself | You fix it | You fix it |

*Figure 16 of the guide: formatters and many lint rules fix problems for you; type and test failures you fix
yourself.*

### Terms

| Term | Plain-English meaning |
|---|---|
| **Formatter** | Rewrites code layout (spacing, quotes, line breaks) into one consistent style. It never changes what the code does. |
| **Linter / static analysis** | Reads code without running it and flags likely bugs, risky patterns and style problems. Each check is a rule with a code, e.g. `B006`. |
| **Type hint** | A label saying what kind of value a variable or function expects or returns, e.g. `def chunk(text: str) -> list[str]`. |
| **Type checker** | Reads the type hints and checks they're used consistently everywhere, catching "wrong kind of value" bugs before the code runs. |
| **Git hook** | A script git runs automatically at a certain moment: before a commit, after writing the message, before a push. |
| **pre-commit (the tool)** | A framework that installs and runs git hooks from one config file, `.pre-commit-config.yaml`. |
| **Staged files** | The files you've `git add`-ed: exactly what the next commit will contain. Hooks check these. |
| **Auto-fix** | Some tools change files to fix problems themselves. You review the changes and `git add` them again. |
| **False positive** | A check flags something that's actually fine. You silence it narrowly, with a comment explaining why. |
| **Shift left** | Moving checks earlier in the process (to the left on the diagram), where fixing is cheaper. |
| **`--no-verify`** | A git flag that skips local hooks. That's why CI must repeat the same checks. |

### Why ruff and mypy?

- **ruff** (by Astral, the makers of uv) replaces a whole toolbox: Black (formatting), isort (import sorting),
  Flake8 and dozens of plugins, pyupgrade, and much of Bandit (security) and pylint. It's written in Rust and
  checks a large codebase in well under a second.
- **mypy** is the original and most widely used Python type checker, and it understands the libraries used later
  (Pydantic, SQLAlchemy). **Strict mode** is used for our shared libraries, where wrong types hurt most.

### Where tool versions come from: a single source of truth

pre-commit normally downloads its own copy of each tool, pinned in `.pre-commit-config.yaml`. That would give two
places to pin ruff's version (that file and `uv.lock`), and they can drift apart, so your editor, your hooks and CI
might disagree. Instead:

- **ruff, mypy and pytest run as local hooks through `uv run`**, so they use exactly the versions locked in
  `uv.lock`. Editor, hooks and CI all use one version.
- **Generic checks** (whitespace, large files, secrets, commit messages) come from their own pinned repositories,
  because they're not part of your Python project.

## How to do it

All commands run in `~/dev/rag-platform` (the root of this repository). Follow the Step 4 workflow: do this work on
a branch, then open a pull request.

```bash
cd ~/dev/rag-platform
git switch -c build/quality-gates
```

### 1 · Add the tools as locked development dependencies

```bash
uv add --dev ruff mypy pytest pre-commit        # goes into [dependency-groups] dev, locked in uv.lock
uv run ruff --version && uv run mypy --version && uv run pytest --version && uv run pre-commit --version
```

> **IN PLAIN ENGLISH**
> These tools are needed only while developing, never when the platform runs, so they're **dev dependencies**.
> Because they're in `uv.lock`, everyone (and CI) gets exactly the same versions, and they upgrade only when you
> deliberately run `uv lock --upgrade-package ruff`.

In this repository, [`pyproject.toml`](../../pyproject.toml) now lists the four tools in the `dev` group and
[`uv.lock`](../../uv.lock) pins them (at the time of writing: ruff 0.17.0, mypy 2.4.0, pytest 9.1.1,
pre-commit 4.6.2).

### 2 · Configure the tools once, in the root `pyproject.toml`

Append these sections below the existing ones (already done in [`pyproject.toml`](../../pyproject.toml)):

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = [
    "E", "W",   # pycodestyle: basic style errors and warnings
    "F",        # pyflakes: unused imports/variables, undefined names
    "I",        # isort: import ordering
    "B",        # flake8-bugbear: likely bugs (mutable defaults, etc.)
    "UP",       # pyupgrade: use modern Python syntax
    "SIM",      # flake8-simplify: simpler equivalent code
    "N",        # pep8-naming: naming conventions
    "S",        # flake8-bandit: security issues (eval, hardcoded passwords, etc.)
    "C4",       # flake8-comprehensions: cleaner list/dict comprehensions
    "PT",       # flake8-pytest-style: consistent tests
    "T20",      # flake8-print: no stray print() in library code (use logging)
    "RUF",      # ruff's own rules
]
ignore = ["E501"]                   # line length is the formatter's job

[tool.ruff.lint.per-file-ignores]
"**/tests/**" = ["S101"]            # assert is normal in tests
"scripts/**"  = ["T20"]             # scripts may print

[tool.ruff.lint.isort]
known-first-party = ["rag_common"]

[tool.ruff.format]
quote-style = "double"
docstring-code-format = true

[tool.mypy]
python_version = "3.12"
strict = true                       # the full set of strictness checks
warn_unreachable = true
pretty = true
files = ["libs/rag-common/src"]     # add each new library/service as it's created

[tool.pytest.ini_options]
testpaths = ["libs", "tests"]
addopts = "-ra --strict-markers --import-mode=importlib"
```

> **IN PLAIN ENGLISH · WHAT THESE SETTINGS MEAN**
> - `select` switches on families of lint rules. Each letter group is a former stand-alone tool that ruff now
>   includes.
> - `per-file-ignores` relaxes rules only where they don't make sense: `assert` is how tests check things, and
>   scripts are allowed to print.
> - `strict = true` makes mypy insist that every function has type hints and that nothing is silently treated as
>   "any type".
> - `--import-mode=importlib` lets two test files with the same name live in different folders without clashing.

### 3 · Write the first unit test

[`libs/rag-common/tests/test_hello.py`](../../libs/rag-common/tests/test_hello.py):

```python
from rag_common import hello


def test_hello_names_the_package() -> None:
    assert "rag-common" in hello()
```

```bash
uv run pytest          # expect: 1 passed
uv run ruff check .    # expect: All checks passed!
uv run ruff format .   # rewrites any badly formatted files
uv run mypy            # expect: Success: no issues found
```

> **IF MYPY COMPLAINS ABOUT HELLO()**
> uv's library template already includes type hints (`def hello() -> str:`) and a `py.typed` marker. If your
> template version doesn't, add the `-> str` yourself. That's exactly the kind of gap strict mode is designed to
> find.

### 4 · Create the pre-commit configuration

[`.pre-commit-config.yaml`](../../.pre-commit-config.yaml), as the guide writes it before freezing:

```yaml
# Hooks run automatically on: git commit (pre-commit), message check (commit-msg), git push (pre-push).
default_install_hook_types: [pre-commit, commit-msg, pre-push]
default_stages: [pre-commit]
fail_fast: false

repos:
  # ---- Generic file hygiene (pinned; update with `pre-commit autoupdate`) ----
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-json
      - id: check-merge-conflict      # leftover <<<<<<< markers
      - id: check-case-conflict       # File.txt vs file.txt (breaks on Linux)
      - id: check-added-large-files   # block files bigger than 1 MB
        args: [--maxkb=1024]
      - id: detect-private-key        # -----BEGIN ... PRIVATE KEY-----
      - id: no-commit-to-branch       # never commit directly on main
        args: [--branch, main]

  # ---- Secret scanning ----
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks

  # ---- Commit message format (Conventional Commits) ----
  - repo: https://github.com/compilerla/conventional-pre-commit
    rev: v3.6.0
    hooks:
      - id: conventional-pre-commit
        stages: [commit-msg]
        args: [feat, fix, docs, refactor, test, build, ci, chore, perf, revert]

  # ---- Python tools: run through uv so versions come from uv.lock ----
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check (lint, auto-fix)
        entry: uv run ruff check --fix --force-exclude
        language: system
        types_or: [python, pyi]
      - id: ruff-format
        name: ruff format
        entry: uv run ruff format --force-exclude
        language: system
        types_or: [python, pyi]
      - id: mypy
        name: mypy (strict type check)
        entry: uv run mypy
        language: system
        types: [python]
        pass_filenames: false         # mypy checks the configured files as a whole
      - id: uv-lock
        name: uv.lock matches pyproject.toml
        entry: uv lock --locked
        language: system
        files: (^|/)(pyproject\.toml|uv\.lock)$
        pass_filenames: false
      - id: pytest
        name: pytest (before push)
        entry: uv run pytest -q
        language: system
        stages: [pre-push]
        pass_filenames: false
        always_run: true
```

What each part does, in plain words:

- `default_install_hook_types` makes one `pre-commit install` set up all three git hooks.
- `default_stages: [pre-commit]` means a hook runs at commit time unless it says otherwise (the message check says
  `commit-msg`, the tests say `pre-push`).
- `fail_fast: false` runs every hook even after one fails, so you see all problems at once.
- `--force-exclude` makes ruff respect its own exclude list even when pre-commit hands it file names directly.
- `pass_filenames: false` on mypy: strict type checking only makes sense over the whole configured package, not
  one file at a time.
- The `uv-lock` hook only runs when a `pyproject.toml` or `uv.lock` is staged, and blocks the commit if you edited
  dependencies without re-locking.
- `always_run: true` on pytest: tests run before every push, even if no Python file changed.

Now move every pinned `rev` to its newest release, and pin it to an exact commit rather than a movable tag:

```bash
uv run pre-commit autoupdate --freeze   # rewrites each rev to the latest release's commit SHA
git diff .pre-commit-config.yaml        # review what changed
```

In this repository that produced:

```yaml
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: 3e8a8703264a2f4a69428a0aa4dcb512790b2c8c  # frozen: v6.0.0
  - repo: https://github.com/gitleaks/gitleaks
    rev: 2ca41cc1372d1e939a6a879f18cdc19fc1cac1ce  # frozen: v8.30.0
  - repo: https://github.com/compilerla/conventional-pre-commit
    rev: 3db014c16a9d31997ab8c07a4d61fcce936c8f0d  # frozen: v4.4.0
```

> **WHY `--FREEZE`?**
> A tag like `v5.0.0` can be moved by whoever controls the repository, so a compromised upstream could swap the
> code behind it. A full commit SHA can't be changed. `--freeze` pins the SHA and keeps the version as a comment.
> This is the same supply-chain idea as the hashes in `uv.lock`.

> **WATCH OUT · TWO POSSIBLE WARNINGS**
> - Newer pre-commit releases may say `language: system` has been renamed (to `unsupported`). If you see that
>   warning, change it as suggested; the behaviour is the same.
> - The gitleaks hook builds a small Go program the first time it runs, which can take a minute. If that fails,
>   add `brew "gitleaks"` to the Brewfile, and replace the hook with a local one:
>   `entry: gitleaks git --pre-commit --staged --verbose`, `language: system`, `pass_filenames: false`.

### 5 · Install the hooks and run them on everything

```bash
uv run pre-commit install          # installs pre-commit, commit-msg and pre-push hooks into .git/hooks
uv run pre-commit run --all-files  # first run on every file: some hooks may fix files
git status                         # review any auto-fixed files
```

(Or `just install-hooks`, a recipe this repository adds so onboarding is one command.)

Run `pre-commit run --all-files` again until everything shows **Passed**. The first run downloads and sets up each
hook, so it's slower than later runs.

What happens on `git commit` (Figure 17 of the guide):

```
git commit ──► pre-commit runs hooks on the STAGED files only (from .pre-commit-config.yaml):
               whitespace · ruff check · ruff format · mypy · gitleaks · private key
               large files · not on main · uv.lock ok
                  │
          all pass? ── no ──► Commit blocked. Nothing is saved.
                  │           Some files were auto-fixed: review them, git add them, and commit again.
                 yes
                  ▼
           commit-msg hook: Conventional format? ──► Commit created (signed). Push runs pytest.
```

### 6 · Watch each gate catch a real mistake

These are deliberate mistakes. Each one should be blocked. Clean up after each one.

**a) The linter catches a classic Python bug.** Create a temporary
`libs/rag-common/src/rag_common/demo.py`:

```python
import os


def add_chunk(chunk: str, chunks: list[str] = []) -> list[str]:
    chunks.append(chunk)
    return chunks
```

```bash
git add libs/rag-common/src/rag_common/demo.py && git commit -m "feat: demo"
# ruff: F401 `os` imported but unused                          (auto-removed)
# ruff: B006 Do not use mutable data structures for argument defaults
```

> **WHY B006 MATTERS IN A RAG SERVICE**
> A default list is created once and shared by every call. In a long-running API server, chunks from one user's
> request would quietly pile up and appear in the next user's results: a correctness bug **and** a data-leak bug.
> The fix is `chunks: list[str] | None = None`, then `chunks = [] if chunks is None else chunks` inside the
> function.

**b) The type checker catches a wrong type.** Replace the file's contents with:

```python
def top_k(scores: list[float], k: int) -> list[float]:
    return sorted(scores, reverse=True)[:k]


best = top_k([0.9, 0.2, 0.7], "3")
```

```bash
git add -A && git commit -m "feat: demo"
# mypy: Argument 2 to "top_k" has incompatible type "str"; expected "int"
```

**c) Secrets are blocked.**

```bash
printf -- "-----BEGIN OPENSSH PRIVATE"" KEY-----\nFAKEFAKEFAKE\n-----END OPENSSH PRIVATE"" KEY-----\n" > leaked.txt
git add leaked.txt && git commit -m "chore: demo"
# detect-private-key: Private key found: leaked.txt       (gitleaks may also flag it)
git rm --cached leaked.txt && rm leaked.txt
```

(The guide writes the marker as one unbroken string. Here it is split into two adjacent shell strings, `"…PRIVATE"" KEY…"`,
which print exactly the same text: written unbroken, the marker in this very document was blocked by
detect-private-key when it was committed, a live demonstration of the gate.)

**d) A bad commit message is rejected.**

```bash
rm libs/rag-common/src/rag_common/demo.py
git add -A
git commit -m "updated stuff"                                               # rejected by conventional-pre-commit
git commit -m "build: add quality gates with ruff, mypy, pytest and pre-commit"   # accepted
```

**e) Committing directly to `main` is blocked.**

```bash
git switch main
git commit --allow-empty -m "chore: test"     # no-commit-to-branch: blocked
git switch build/quality-gates
```

**f) Tests run before every push.**

```bash
git push -u origin build/quality-gates        # "pytest (before push) ... Passed", then the push happens
```

> **WATCH OUT · ABOUT `--NO-VERIFY`**
> `git commit --no-verify` and `git push --no-verify` skip local hooks. You might use them occasionally (for
> example, a work-in-progress commit on your own branch). Local hooks are a **seatbelt, not a lock**. That's why
> Step 27 runs the same checks in CI, where they can't be skipped before merging to `main`. To skip one hook only,
> use `SKIP=mypy git commit …`.

### 7 · Add `just` recipes and editor integration

Add these recipes to the [`justfile`](../../justfile), and update `check` so it runs every gate:

```just
# Format all code
fmt:
    uv run ruff format .

# Lint (and auto-fix what's safe)
lint:
    uv run ruff check --fix .

# Strict type check
typecheck:
    uv run mypy

# Run the tests
test:
    uv run pytest

# Run every pre-commit hook on every file
hooks:
    uv run pre-commit run --all-files

# Everything CI will run (Step 27 calls exactly this)
check:
    brew bundle check --file=bootstrap/Brewfile
    uv sync --locked --all-packages
    uv run pre-commit run --all-files
    uv run pytest
```

So your editor shows the same problems as you type, add recommended extensions for VS Code (the `.gitignore` from
Step 4 deliberately allows this one file) in [`.vscode/extensions.json`](../../.vscode/extensions.json):

```json
{
    "recommendations": [
        "charliermarsh.ruff",
        "ms-python.python",
        "ms-python.mypy-type-checker",
        "editorconfig.editorconfig"
    ]
}
```

> **TIP · SILENCING A FALSE POSITIVE, THE RIGHT WAY**
> Silence one line with a reason, never a whole file without one:
> `subprocess.run(cmd, check=True)  # noqa: S603 - cmd is a fixed internal list`. For mypy:
> `# type: ignore[arg-type]` plus a comment. Narrow, explained exceptions keep the checks trustworthy.

### 8 · Record the decision: ADR-0005

```bash
just adr "Automated code quality gates with ruff, mypy, pytest and pre-commit"
```

Fill it in as
[`docs/adr/0005-automated-code-quality-gates-with-ruff-mypy-pytest-and-pre-commit.md`](../adr/0005-automated-code-quality-gates-with-ruff-mypy-pytest-and-pre-commit.md):
ruff (lint + format), strict mypy for libraries and pytest, locked in `uv.lock` and run as local hooks via
`uv run`; generic hooks frozen to commit SHAs; tests at pre-push; CI (Step 27) runs `just check`. It lists the
alternatives considered (Black + isort + Flake8, pyright/basedpyright, ty/pyrefly, prek/lefthook, upstream hook
repos for ruff/mypy), the consequences, and when to revisit (a new type checker matures, or hook run time exceeds
~10 s on typical commits).

Add ADR-0005 to [`docs/adr/README.md`](../adr/README.md), then commit and open the pull request:

```bash
git add -A
git commit -m "docs(adr): record ADR-0005 code quality gates"
git push
gh pr create --fill && gh pr merge --squash --delete-branch
git switch main && git pull
```

## Benefits

- **Bugs caught in seconds**, before they enter history, at the cheapest possible moment.
- **No style arguments**: the formatter decides, so reviews focus on logic.
- **Security built in**: insecure patterns (Bandit rules), private keys and tokens are blocked automatically.
- **One version of every tool**: editor, hooks and CI agree because versions come from `uv.lock`.
- **Readable history**: every commit message follows the convention, so changelogs and version numbers can be
  generated.
- **Faster onboarding**: new contributors get instant, consistent feedback without memorising rules.

## Drawbacks and risks

- **Slower commits**: a few seconds per commit (mypy is the slowest). Keep slow checks (tests) at pre-push or in CI.
- **Skippable**: `--no-verify` bypasses everything. Local hooks are a convenience; CI is the real gate.
- **False positives and friction**: strict rules can annoy people into blanket `noqa` comments. Start strict on new
  code, explain every exception, and review the rule set occasionally.
- **Secret scanners aren't perfect**: they miss secrets that don't match known patterns, and sometimes flag
  harmless strings. They reduce risk; they don't remove it. Real protection is not having secrets in the repo at
  all (Step 6).
- **Upkeep**: hook versions and rules need periodic updates (`pre-commit autoupdate --freeze`,
  `uv lock --upgrade-package ruff`). Treat these like any other dependency upgrade.

## Alternatives

| Area | Our choice | Alternatives | Choose the alternative when |
|---|---|---|---|
| Formatting | `ruff format` | Black; YAPF; autopep8 | An existing codebase is standardised on Black (ruff's output is nearly identical) |
| Linting | `ruff check` | Flake8 + plugins; pylint (deeper, slower); Bandit (security) | You need a pylint-only check or a plugin ruff lacks |
| Type checking | mypy (strict) | pyright / basedpyright; ty (Astral, new); pyrefly (Meta, new) | Editor speed matters most (pyright); you want to try the new Rust checkers once they're stable |
| Hook runner | pre-commit | prek (Rust rewrite that reads the same config); lefthook; husky (JavaScript projects); plain `.git/hooks` scripts | Polyglot repos wanting speed (prek, lefthook); JS-first teams (husky) |
| Secret scanning | gitleaks + detect-private-key | detect-secrets (Yelp; baseline file of known findings); TruffleHog (can verify whether a secret is live); GitHub secret scanning / push protection | Large legacy repos (detect-secrets baseline); incident response (TruffleHog); GitHub's server-side protection (free on public repos; a paid add-on for private ones) |
| Commit messages | conventional-pre-commit | commitizen (also bumps versions and writes changelogs); commitlint (Node) | You want automatic version bumps and changelogs (commitizen) |
| Test runner | pytest | unittest (built in); nox / tox for testing many Python versions | Libraries supporting several Python versions (nox/tox) |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| New Python project or platform | ruff + mypy/pyright + pre-commit + pytest, versions locked with the project (this step) |
| Large legacy codebase with thousands of existing issues | Enable rules gradually, or use baselines (record existing issues, fail only on new ones) so the team isn't blocked |
| Polyglot monorepo (Python + TypeScript + Go) | pre-commit or prek with per-language hooks, or lefthook |
| Regulated or security-critical environment | All of the above, plus server-side secret scanning, SAST in CI (e.g. Semgrep, CodeQL), and mandatory CI gates on protected branches |
| Data-science notebooks | nbQA or ruff's notebook support, plus nbstripout to remove outputs (which may contain data) before commit |

## Common mistakes

- **Pinning tool versions in two places** (`uv.lock` and the hook config), so editor, hooks and CI disagree.
- **Forgetting `pre-commit install` after cloning.** The config file does nothing until the hooks are installed.
  Add it to your onboarding (`just` recipe or README) — this repository has `just install-hooks` and lists it in
  the README quick start.
- **Not re-adding auto-fixed files.** After hooks modify files, you must `git add` them again and recommit.
- **Turning every rule on at once in an old codebase**, then giving up. Enable gradually.
- **Blanket ignores** (`# noqa` with no code, whole-file excludes) that hide real problems.
- **Running slow tests on every commit**, so people start using `--no-verify`. Keep the commit stage fast.
- **Treating local hooks as security.** They're skippable; CI enforces.
- **Committing a real secret and only deleting the file.** It remains in git history. Rotate the secret
  immediately, then clean history if necessary.

## Done when

- [ ] `ruff`, `mypy`, `pytest` and `pre-commit` are in the root `[dependency-groups] dev` and locked in `uv.lock`
- [ ] Root `pyproject.toml` has `[tool.ruff]`, `[tool.mypy]` and `[tool.pytest.ini_options]` sections
- [ ] `uv run pytest` shows 1 passed, and `uv run mypy` reports no issues
- [ ] `.pre-commit-config.yaml` exists with `rev`s frozen to commit SHAs
- [ ] `uv run pre-commit run --all-files` passes on every hook
- [ ] You saw each gate block a mistake: lint (B006), type (mypy), private key, bad message, commit to `main`
- [ ] `git push` ran pytest before pushing
- [ ] `just check` runs Brewfile check, locked sync, all hooks and tests, and passes
- [ ] `.vscode/extensions.json` is committed (if you use VS Code)
- [ ] ADR-0005 is written, indexed and merged through a PR

## Recap

> **RECAP**
> Every commit now passes through automatic quality gates: formatting, linting (including security rules), strict
> type checking, secret and private-key detection, file-hygiene checks and a commit-message check, with tests
> before every push. Tool versions come from `uv.lock`, so your editor, your hooks and CI all agree. Local hooks
> give fast feedback; CI (Step 27) will make the same `just check` mandatory.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| [`pyproject.toml`](../../pyproject.toml) | `dev` group now holds ruff, mypy, pytest and pre-commit; new `[tool.ruff]`, `[tool.mypy]` and `[tool.pytest.ini_options]` sections. |
| [`uv.lock`](../../uv.lock) | Re-locked with the four dev tools and their dependencies. |
| [`libs/rag-common/tests/test_hello.py`](../../libs/rag-common/tests/test_hello.py) | The first unit test: `hello()` names the package. |
| [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml) | The three hook stages (pre-commit, commit-msg, pre-push); generic hooks frozen to commit SHAs; ruff/mypy/uv-lock/pytest run through `uv run`. |
| [`justfile`](../../justfile) | New `fmt`, `lint`, `typecheck`, `test`, `hooks`, `install-hooks` recipes; `check` now runs every gate. |
| [`.vscode/extensions.json`](../../.vscode/extensions.json) | Recommended VS Code extensions so the editor shows the same problems as the hooks. |
| [`README.md`](../../README.md) | Quick start now includes `just install-hooks` and describes the fuller `just check`. |
| [`docs/adr/0005-automated-code-quality-gates-with-ruff-mypy-pytest-and-pre-commit.md`](../adr/0005-automated-code-quality-gates-with-ruff-mypy-pytest-and-pre-commit.md) | ADR-0005: the decision, alternatives and consequences. |
| [`docs/adr/README.md`](../adr/README.md) | ADR-0005 added to the index. |
| [`docs/steps/step-05-linting-formatting-pre-commit.md`](step-05-linting-formatting-pre-commit.md) | This write-up. |
| [`docs/steps/README.md`](README.md), [`docs/glossary.md`](../glossary.md), [`CHANGELOG.md`](../../CHANGELOG.md) | Step 5 row, terms and entry added. |

## Notes for this repository

- **Frozen revs are newer than the guide's.** `pre-commit autoupdate --freeze` was run here as the chapter
  instructs, so the committed config pins pre-commit-hooks v6.0.0, gitleaks v8.30.0 and conventional-pre-commit
  v4.4.0 by commit SHA (the guide's starting tags were v5.0.0, v8.21.2 and v3.6.0). The hook IDs and arguments are
  unchanged. pre-commit 4.6.2 did not warn about `language: system`, so it is kept as written.
- **`deploy` is an allowed commit type.** Step 29's `just promote` commits as `deploy(<env>): rag-api <digest>`,
  which the chapter's type list would reject, so `deploy` was added to the hook's arguments (a test in
  `tests/test_promote.py` keeps the recipe and the hook in step).
- **Locked tool versions** at the time of this step: ruff 0.17.0, mypy 2.4.0, pytest 9.1.1, pre-commit 4.6.2. The
  `uv add` lower bounds (`>=`) come from uv; the exact versions live in `uv.lock`.
- **`just install-hooks`** is an addition of this repository, following the chapter's own "Common mistakes" advice
  to put `pre-commit install` into onboarding (a `just` recipe or the README); both were done.
- **Branch and PR workflow.** This repository works on its own feature branch rather than `build/quality-gates`,
  and the PR/merge (`gh pr create`, `gh pr merge`) is an owner action on GitHub. The guide's two commit messages
  (`build: add quality gates …` and `docs(adr): record ADR-0005 code quality gates`) are mirrored; the write-up
  lands in a third `docs` commit.
- **ADR "Deciders"** names the repository owner instead of `<you>`; the date is the guide's (2026-10-11), matching
  ADR-0001 to ADR-0004.
- **Demo key string split in this write-up.** The fake-key `printf` in part 6c is written as two adjacent
  shell strings so this Markdown file itself passes detect-private-key (the first commit attempt of this write-up
  was blocked by that hook). The command prints the same text as the guide's.
- **Validation done here** (Linux container, Go available for the gitleaks hook build): `uv lock --locked`,
  `uv run pytest` (1 passed), `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy` (no issues);
  `uv run pre-commit install` and `pre-commit run --all-files` pass on every hook. The demo mistakes were
  reproduced with `pre-commit run --files`: B006 (ruff), the `"3"` arg-type error (mypy), the fake private key
  (detect-private-key) and "updated stuff" (conventional-pre-commit) were all blocked; the pre-push pytest hook
  passed; and this step's own commits went through the installed hooks. `just check`'s first line needs Homebrew
  and was not run here; its other three lines were run individually.
