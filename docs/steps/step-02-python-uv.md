# Step 2 · Python toolchain with uv

*Step 2 of 38 · Phase A · Workstation*

## At a glance

| | |
|---|---|
| **Goal** | Install uv, use it to install your own copy of Python, set safe global settings, and learn the four ideas every Python project depends on. |
| **Time** | About 45 minutes, including the hands-on lab. |
| **You'll end up with** | Python 3.12 managed by uv, a global uv config, and practical experience of locking, syncing and catching "drift". |
| **New words** | Interpreter, virtual environment, dependency, transitive dependency, lockfile, hash, wheel, PEP. |

## The big idea

> **ANALOGY · Shopping list, receipt and pantry**
> Your shopping list says "milk, at least 1 litre, any brand". That's `pyproject.toml`: what you're willing to
> accept.
> The itemised receipt says exactly which brand, size and batch you bought, with a barcode for each item.
> That's `uv.lock`: what you actually got, with a fingerprint for every package.
> The pantry is where the items physically sit, ready to use. That's `.venv`: the installed packages. If the
> pantry is emptied, you restock it exactly from the receipt.
> uv is the one tool that writes the list, produces the receipt and stocks the pantry.

uv, made by Astral (the makers of the Ruff linter), replaces six older tools at once: **pip** (installs packages),
**venv** and **virtualenv** (create isolated environments), **pip-tools** (lockfiles), **pyenv** (switches
Python versions) and **pipx** (installs command-line tools written in Python).

## What we're doing

1. Install uv through the Brewfile.
2. Use uv to install your own Python interpreter, separate from macOS's Python and Homebrew's Python.
3. Write a global uv config that controls where Python comes from, and where packages could come from in a
   company setting.
4. Build a small throwaway lab project to learn the four ideas the whole platform relies on: interpreter, virtual
   environment, dependency spec and lockfile.

## Why we're doing this

Step 1 left a gap: Homebrew can't pin versions precisely. In Python that matters far more, because a RAG service
uses hundreds of packages, and most of them are **transitive**: packages your packages need, which you never
chose yourself. For example, `langchain` pulls in `pydantic`, which pulls in `pydantic-core`, and so on. If any of
those versions changes quietly, a pipeline that worked yesterday can break today even though you changed nothing.

uv solves this with a **lockfile**: a file recording the exact version and a cryptographic hash (a unique
fingerprint) of every package in the full tree, for every operating system. Anyone who runs `uv sync` from that
lockfile gets byte-for-byte identical packages.

**Direct vs transitive dependencies** (the guide's Figure 4, illustrative; run `uv tree` to see your real tree):

```text
your project
├── httpx                 (direct: you asked for it)
│   ├── anyio             (transitive: a dependency of a dependency)
│   ├── certifi
│   ├── httpcore
│   │   └── h11
│   └── idna
├── pydantic              (direct)
│   ├── pydantic-core
│   ├── annotated-types
│   ├── typing-extensions
│   └── typing-inspection
└── pytest  (dev only)    (direct, development only)
    └── pluggy, iniconfig, …
```

You chose three packages; everything underneath came along automatically. The lockfile pins **all** of them.

| Why it matters | What it means in practice |
|---|---|
| **Reproducibility** | Your laptop, CI and the production container all install exactly the same versions. When an evaluation score changes, you know your code changed it, not a dependency drifting underneath you. |
| **Supply-chain security** | The hashes in the lockfile mean a package that gets swapped on PyPI (the public Python package store) fails to install instead of silently running. |
| **Auditability** | The lockfile is a precise list of every package. In Step 27 it becomes the input to your SBOM (software bill of materials) and vulnerability scanner. |
| **Speed** | uv is written in Rust and keeps one shared download cache. Environments rebuild in seconds instead of minutes, which matters when CI rebuilds them hundreds of times a week. |

> **WHY NOT JUST USE HOMEBREW'S PYTHON?**
> When `brew upgrade` moves `python@3.12` to a new patch release, the virtual environments built on it can
> break, because they still point at the old interpreter's location. uv-managed Pythons change only when you
> change them.

> **IN A COMPANY**
> Reproducible, hash-verified installs are what let a team say "the model scored 0.82 because of this code
> change" with confidence, and what security teams need to answer "exactly which packages are running in
> production?". Companies also route all package downloads through an internal mirror (see part 3 below).

## Key ideas: the four building blocks

| Concept | Plain-English meaning | Where it lives |
|---|---|---|
| **Interpreter** | The `python` program itself: the engine that reads and runs Python code, e.g. CPython 3.12.x. | `~/.local/share/uv/python/` |
| **Virtual environment** | A private folder of packages for one project, tied to one interpreter, so projects never mix their packages. Like a separate toolbox per job. | `<project>/.venv/` (never committed to git) |
| **Dependency spec** | What you want, written as acceptable ranges, e.g. `httpx>=0.27`. | `pyproject.toml` (committed) |
| **Lockfile** | What you got: exact versions and hashes for the full tree. | `uv.lock` (committed) |

**The uv workflow** (the guide's Figure 5):

```text
                      uv add <package> = edit + lock + sync in one go

 pyproject.toml   ── uv lock ──▶   uv.lock            ── uv sync ──▶   .venv/
 What you'll ACCEPT                What you GOT                        What's INSTALLED
 Ranges, e.g. httpx>=0.28          Exact versions of every package     The actual packages, ready to use
 Written by you (via uv add)       + fingerprints (hashes)             Disposable: rebuild any time
 Commit to git · shopping list     Commit to git · itemised receipt    Never commit · the pantry

 uv run <command> → checks the pantry matches the receipt (syncs if needed), then runs your command inside .venv
```

You edit your intent, `uv lock` turns it into an exact receipt, and `uv sync` makes the installed packages match
the receipt. `uv add` does all three; `uv run` syncs and then runs.

Other words you'll meet in this step:

| Term | Plain-English meaning |
|---|---|
| **Package / dependency** | Someone else's code your project uses. A dependency is a package your project needs in order to work. |
| **Transitive dependency** | A dependency of a dependency: something you never asked for directly but that comes along because a package you chose needs it. |
| **Hash** | A short fingerprint calculated from a file's contents. Change one byte and the fingerprint changes completely, so it proves a file hasn't been tampered with. |
| **Wheel** | A pre-built Python package, ready to install, like flat-pack furniture. Without a wheel, pip has to build from source (cut the timber yourself), which is slow and often fails for scientific packages. |
| **PEP** | "Python Enhancement Proposal": an official Python standard. PEP 621 defines `pyproject.toml`; PEP 735 defines dependency groups; PEP 668 protects system Pythons from accidental changes. |
| **Dev dependency** | A package needed only while developing (e.g. `pytest` for tests), not when the app runs in production. |

> **IN PLAIN ENGLISH**
> `pyproject.toml` is what you'll accept; `uv.lock` is exactly what you got; `.venv` is what's installed right
> now and can be thrown away and rebuilt from `uv.lock` at any time.

## How to do it

All commands run in the macOS Terminal. `~/dev/rag-platform/` is the root of this repository.

### 1 · Add uv to the Brewfile and install it

Following the Step 1 rule (list first, install second), add this to the Brewfile. In this repo it is already in
[`bootstrap/Brewfile`](../../bootstrap/Brewfile):

```ruby
# ---- Python toolchain (Step 2) ----
brew "uv"                   # Python versions, venvs, dependency locking, tool installs; replaces pip/pyenv/pipx/pip-tools
```

```bash
cd ~/dev/rag-platform/bootstrap
brew bundle --file=Brewfile
uv --version
```

> **WATCH OUT · Pick one way to update uv**
> uv has its own installer script and a `uv self update` command. Pick one install method and stick with it.
> Since we installed with Homebrew, always upgrade with `brew upgrade uv`, never `uv self update`, or the two
> methods will conflict.

### 2 · Install a managed Python interpreter

```bash
uv python install 3.12
uv python list --only-installed
```

> **WHY PYTHON 3.12?**
> For an AI/ML stack, the deciding question is whether the big packages publish pre-built wheels for that Python
> version. The packages that matter here are mlx, torch, sentence-transformers, spaCy (used by Presidio),
> pyarrow and grpcio. If a wheel is missing, installation falls back to building from source, which is slow and
> fragile. 3.12 has the most mature wheel coverage across that whole stack. Newer versions (3.13, 3.14) are fine
> for many packages, but the slowest package in your stack decides which version you can use.
> How to check a package yourself: open its page on pypi.org → *Download files*, and look for a file named like
> `cp313-…-macosx_…_arm64.whl` (here `cp313` means Python 3.13). Moving to a newer Python later is a deliberate
> decision you'll record as an ADR in Step 4.

Confirm the interpreter is native Apple Silicon. MLX will not run under Rosetta emulation:

```bash
uv run --python 3.12 python -c "import platform, sys; print(platform.machine(), sys.version)"
# expected: arm64 3.12.x ...
```

### 3 · Write the global uv config

Create the file `~/.config/uv/uv.toml` (create the folder first). This repo keeps the reference copy at
[`bootstrap/home/.config/uv/uv.toml`](../../bootstrap/home/.config/uv/uv.toml), so you can simply copy it:

```bash
mkdir -p ~/.config/uv
cp ~/dev/rag-platform/bootstrap/home/.config/uv/uv.toml ~/.config/uv/uv.toml
```

The settings it contains:

```toml
# Use only uv-managed interpreters: never Apple's /usr/bin/python3 or Homebrew's.
python-preference = "only-managed"

# Don't download interpreters silently; installing one is a deliberate act (`uv python install`).
python-downloads = "manual"
```

- **`only-managed`**: Python always comes from exactly one place, so the question "which Python is this?" always
  has the same answer.
- **`manual`**: in a governed environment, nothing downloads unless someone chose to download it. That's the same
  reasoning as turning off Homebrew analytics in Step 1.

> **IN A COMPANY · Internal package mirror**
> Companies usually don't let machines download straight from public PyPI. Instead they use an internal mirror
> (a scanned, approved copy). You'd add the lines below to the same file. You don't need them today, but know
> where they go (they are already in the reference copy, commented out):
>
> ```toml
> # [[index]]
> # url = "https://artifactory.example.com/api/pypi/pypi-remote/simple"
> # default = true
> ```

### 4 · Lab: learn the workflow on a throwaway project

```bash
mkdir -p ~/dev/sandbox && cd ~/dev/sandbox
uv init uv-lab --python 3.12
cd uv-lab
ls -a
# .git        .gitignore           .python-version   README.md   main.py   pyproject.toml
```

`uv init` creates a tiny project: a `pyproject.toml` (the list), a `.python-version` file pinning the interpreter,
a starter `main.py`, a README, and even its own git repository with a `.gitignore` that already excludes `.venv`.

#### A) Add dependencies and look at what changed

```bash
uv add httpx pydantic        # runtime dependencies
uv add --dev pytest          # development-only dependency (goes in a dependency group)
cat pyproject.toml           # print the file
```

You'll see lines like `"httpx>=0.28.1"`. Those are ranges: what you're willing to accept. `pytest` appears in a
separate `[dependency-groups] dev = [...]` section (the PEP 735 standard), so it is never installed in
production. Now look at the receipt:

```bash
grep -A3 'name = "httpx"' uv.lock   # exact version, source, and sha256 hashes
uv tree                              # the full dependency tree, including transitive dependencies
```

> **WHAT YOU SHOULD NOTICE**
> You asked for 2 packages (plus pytest), but `uv tree` lists many more. Those extras are the transitive
> dependencies, and the lockfile pins every one of them.

#### B) The environment is disposable; the lockfile is the source of truth

```bash
rm -rf .venv                 # throw the pantry away
time uv sync                 # rebuilt from uv.lock, mostly from cache, typically well under a second
uv run python -c "import httpx, pydantic; print(httpx.__version__, pydantic.__version__)"
```

#### C) Watch CI catch "drift"

**Drift** means the list and the receipt no longer match. Simulate it: open `pyproject.toml`, add `"rich"` to the
`dependencies` list by hand, save it, and *don't* run `uv lock`. Then:

```bash
uv sync --locked
# error: the lockfile needs to be updated, but --locked was provided
```

That's exactly the check your CI pipeline will run in Step 27. If someone changes the dependencies without
updating the lockfile, the build fails. Fix it the proper way:

```bash
uv lock && uv sync --locked  # now passes
```

#### D) Upgrade on purpose

```bash
uv lock --upgrade-package httpx   # move ONE package, review the change, commit
# uv lock --upgrade               # moves EVERYTHING; do this rarely and deliberately
```

#### E) Run a tool without adding it to the project

```bash
uvx ruff --version           # one-off run in a temporary, isolated environment
uv tool install ruff         # install a standalone CLI tool globally, isolated from your projects
```

That covers the whole workflow. Delete the lab when you're finished (`rm -rf ~/dev/sandbox/uv-lab`); the real
repository starts in Step 4.

> **TIP · Replay the lab with one command**
> This repo adds [`bootstrap/labs/uv-lab.sh`](../../bootstrap/labs/uv-lab.sh), which performs parts 2 and A–E in
> order, checks that `uv sync --locked` really fails on drift and passes after `uv lock`, and deletes the lab at the
> end. Run it after doing the lab by hand, or on a new machine to prove uv works:
> `bash bootstrap/labs/uv-lab.sh` (options: `SANDBOX_DIR=…`, `KEEP_LAB=1`, `SKIP_TOOL_INSTALL=1`).

### 5 · Optional: activate the environment automatically with direnv

`uv run <command>` always works without "activating" anything, and it's the recommended way to run things. If
you'd rather have `python` and `pytest` work directly whenever you enter a project folder, add an `.envrc` file
to that project:

```bash
# File · <project>/.envrc
[ -d .venv ] && source .venv/bin/activate
```

```bash
direnv allow                 # direnv asks permission before running any .envrc, for safety
```

This relies on the `direnv hook zsh` line added to `~/.zshrc` in Step 1. The repository's own `.envrc` arrives in
Step 6.

## Benefits

- **One tool instead of six.** Fewer tools means less to learn, less to break, and less to audit.
- **One lockfile for every platform.** A single `uv.lock` works on macOS arm64 and the Linux x86_64/arm64
  containers you'll build later. With pip you'd need a separate lock per platform.
- **Hash-verified installs** out of the box.
- **Speed:** parallel downloads, a global cache, and hard links instead of copies, so 20 projects that use torch
  don't use 20 times the disk space.
- **Standards-based.** `pyproject.toml` and dependency groups follow official Python standards (PEP 621 and
  PEP 735), so your project isn't trapped in a uv-only format.
- **Workspaces.** Several packages in one repository can share one lockfile. You'll use this in Step 4 for
  `services/` and `libs/`.

## Drawbacks and risks

- **Young and fast-moving.** uv adds features and changes behaviour often. Pin the uv version in CI (Step 27) and
  read the changelog before upgrading.
- **One company maintains it.** Astral is VC-funded, so ask what happens if it changes direction. Mitigation:
  everything you write (`pyproject.toml`, dependency groups) follows Python standards, so moving to another
  standards-based tool such as PDM is a modest effort. `uv.lock` itself is uv-specific, though.
- **Python packages only.** uv can't install system libraries such as CUDA, GDAL or Tesseract. Those come from
  Homebrew or the container image. conda/pixi can manage both (see Alternatives).
- **The interpreters are built by a third party.** uv's Pythons come from the python-build-standalone project,
  not python.org. They're widely used and reliable, but a strict security team may want them reviewed or rebuilt
  internally.
- **A lockfile can preserve a vulnerability.** Locking also keeps known-vulnerable versions in place until you
  upgrade. The fix is scheduled upgrades plus scanning: Renovate/Dependabot and pip-audit in Step 27.

## Alternatives

| Tool | What it is, in plain words | Choose it when |
|---|---|---|
| **uv** (our choice) | All-in-one: interpreters, environments, locking, tools. | New projects in 2025–26 when you want speed, standards and one tool. |
| **pip + venv** | Python's built-in basics. | Tiny scripts, or places where you can't install anything. No real lockfile: `pip freeze` records versions but no hashes, and only for one platform. |
| **pip-tools** (`pip-compile`) | Adds lockfiles (a `requirements.txt` with hashes) on top of pip. | Existing pip-based codebases that need locking without changing their workflow. |
| **Poetry** | A mature, opinionated project manager with its own lockfile. | Many existing codebases use it. Slower than uv; historically used non-standard metadata (closer to the standards since Poetry 2). |
| **PDM / Hatch** | Standards-based project managers. | Hatch is popular for publishing libraries; PDM is the closest alternative to uv's model. |
| **pyenv** | Only switches between Python versions. | Older setups. `uv python install` replaces it. |
| **conda / mamba / pixi** | Manage Python *and* system libraries (C/C++, CUDA, GDAL) from the conda-forge channel. | Scientific stacks with heavy native libraries, or GPU/CUDA work on Linux. pixi is the modern, fast option with lockfiles. |
| **Nix** | Manages the whole system reproducibly, Python included. | When you've already adopted Nix in Step 1. |
| **Rye** | Astral's earlier tool. | Don't. It has been folded into uv. |

> **THE MAIN TRADE-OFF**
> Choose uv when your dependencies are mostly Python wheels. Choose conda/pixi when they're mostly native system
> libraries. On a Mac with MLX, both mlx and torch ship as ordinary PyPI wheels, so uv wins.

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Learning lab, startup, or any new Python service | uv |
| Monorepo with several services sharing libraries | uv workspaces: one lockfile, so every service uses the same version of each shared package |
| Large existing Poetry codebase | Leave it. Migrating has a cost; switch only when speed or workflow problems actually hurt. |
| GPU training on Linux with CUDA, cuDNN or NCCL | pixi/conda, or an NVIDIA base container combined with uv |
| Regulated enterprise with no public internet | uv pointed at an internal mirror (Artifactory/Nexus), pre-approved interpreters, `python-downloads = "never"` |
| Protecting against brand-new malicious packages | uv's `exclude-newer` setting refuses any package version published after a chosen date. Some teams lock about a week behind, so the community has time to spot bad releases before they reach production. |

## Common mistakes

- **Running `pip install` against the system or Homebrew Python.** You'll see `error: externally-managed-environment`
  (PEP 668). That error is protecting you; don't override it with `--break-system-packages` on your Mac.
- **Committing `.venv/`.** It's machine-specific. Commit `pyproject.toml` and `uv.lock`, never the environment
  folder.
- **Not committing `uv.lock`.** Without it you have no reproducibility. For applications and services, always
  commit it.
- **Using `uv pip install` inside a uv project.** That's uv's pip-compatibility mode. It changes `.venv` without
  updating `uv.lock`, so the pantry drifts from the receipt. In projects, use `uv add`.
- **Activating one project's venv and then working in another**, so packages land in the wrong place. `uv run`
  avoids this entirely.
- **Running `uv lock --upgrade` and committing without reviewing the changes.** Treat lockfile changes like code
  changes: review them.
- **Mixing conda and uv in the same environment.** Each keeps its own record of what's installed, and they will
  conflict.

## Done when

- [ ] The `uv` line is in the Brewfile, and `brew bundle check` passes
- [ ] `uv python list --only-installed` shows 3.12
- [ ] The interpreter check in part 2 prints `arm64`
- [ ] `~/.config/uv/uv.toml` exists with `only-managed` and `manual`
- [ ] In the lab, you saw `uv sync` rebuild a deleted `.venv`
- [ ] In the lab, you saw `uv sync --locked` fail on drift, then pass after `uv lock`
- [ ] In the lab, you saw `uv tree` show the transitive dependencies
- [ ] You can explain the difference between `pyproject.toml` and `uv.lock` in one sentence: the first is what
      you'll accept; the second is exactly what you got.

## Recap

> **RECAP**
> You installed uv and a uv-managed Python 3.12, locked down where interpreters come from, and practised the core
> cycle: list → lock → sync. You saw that `.venv` is disposable, `uv.lock` is the source of truth, and
> `uv sync --locked` catches drift: the same check CI will enforce later.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| [`bootstrap/Brewfile`](../../bootstrap/Brewfile) | Appended the "Python toolchain (Step 2)" section with `brew "uv"`. |
| [`bootstrap/home/.config/uv/uv.toml`](../../bootstrap/home/.config/uv/uv.toml) | Reference copy of the global uv config (`only-managed` interpreters, `manual` downloads, commented-out company mirror). Copied to `~/.config/uv/uv.toml` during workstation setup. |
| [`bootstrap/labs/uv-lab.sh`](../../bootstrap/labs/uv-lab.sh) | Replays the Step 2 lab (install Python 3.12, arch check, parts A–E) in `~/dev/sandbox/uv-lab`, asserting that drift is caught, then deletes the lab. |
| [`docs/steps/step-02-python-uv.md`](step-02-python-uv.md) | This write-up. |
| [`docs/steps/README.md`](README.md) | Step index; Step 2 row added. |
| [`docs/glossary.md`](../glossary.md) | Step 2 terms added. |
| [`CHANGELOG.md`](../../CHANGELOG.md) | Step 2 entry added. |

## Notes for this repository

- `~/.config/uv/uv.toml` lives outside the project, so the repo keeps a **reference copy** at
  `bootstrap/home/.config/uv/uv.toml` (mirroring the path under `~`). Copy it to `~/.config/uv/uv.toml` during
  workstation setup. The company mirror lines are included but commented out, exactly as the guide says ("not
  needed now").
- The lab project is throwaway and lives in `~/dev/sandbox/`, outside the repository, so nothing from it is
  committed. `bootstrap/labs/uv-lab.sh` is an addition of this repository (not in the guide) that scripts the
  same commands so the lab can be replayed and checked automatically.
- The optional `<project>/.envrc` from part 5 is shown above but not committed here: the repository's real
  `.envrc` is created in Step 6.
- Validation done here (Linux x86_64 container, no Homebrew): the Brewfile parses as Ruby (`ruby -c`), `uv.toml`
  parses as TOML, `uv-lab.sh` passes `bash -n`, and the lab script ran end to end with
  `UV_CONFIG_FILE=bootstrap/home/.config/uv/uv.toml` (uv 0.11, managed CPython 3.12.13): `uv sync` rebuilt the
  deleted `.venv` in ~0.06 s, `uv sync --locked` failed on the hand-added `rich` and passed after `uv lock`. The
  `arm64` check and `brew bundle` must be run on the Mac.
