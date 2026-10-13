# Step 1 · Homebrew and the Brewfile

*Step 1 of 38 · Phase A · Workstation*

## At a glance

| | |
|---|---|
| **Goal** | Install Apple's developer tools and Homebrew, and record every tool you install in a file called a Brewfile. |
| **Time** | About 30–45 minutes (mostly downloads). |
| **You'll end up with** | A working package manager, eight everyday command-line tools, and a Brewfile that can rebuild them on any Mac with one command. |
| **New words** | Command Line Tools, compiler, Homebrew, package manager, Brewfile, PATH, analytics, infrastructure as code. |

## The big idea

> **ANALOGY · A shopping list instead of shopping from memory**
> Imagine stocking a new kitchen. You could walk around the shop picking things up from memory. Next time you
> move house you'd forget half of them. Or you could write a shopping list, keep it, and hand it to anyone who
> needs to stock an identical kitchen.
> Homebrew is the shop: an "app store" for developer tools that you use from the Terminal. The Brewfile is your
> shopping list. The command `brew bundle` hands the list to the shop, and the shop installs everything on it that
> you don't already have.

Installing tools is easy. The real lesson of this step is the habit: **never install something by hand without
writing it in the list first.**

## What we're doing

1. Install Apple's Command Line Tools: the compiler, git and other basic building blocks almost everything else
   needs.
2. Install Homebrew, the standard package manager for macOS.
3. Turn off Homebrew's analytics (usage reports sent back to Homebrew).
4. Create a Brewfile listing the general-purpose tools the platform needs.
5. Install everything from it and check the result.

## Why we're doing this

> **WHY THIS MATTERS**
> If your setup lives only in your memory and your shell history, it is lost the moment your Mac dies, and it can't
> be checked by anyone else. Writing it in a file makes it rebuildable, reviewable and auditable.

- **Reproducibility.** If your Mac dies, or a colleague joins, `brew bundle` rebuilds the same set of tools in
  minutes. Without the file, your setup exists only in your memory and your shell history.
- **This is "infrastructure as code" in its smallest form.** Infrastructure as code means the environment is
  defined in version-controlled files, not set up by hand. It's the same idea behind Docker Compose (Step 3
  onwards), Kubernetes manifests (Step 29) and Terraform in real companies. Starting the habit now makes it
  natural later.
- **Auditability.** Security teams ask "what software is on this machine, and why?" The Brewfile answers that.
  Once it's in git (Step 4), the history shows who added what, and when.
- **Onboarding.** In real teams the standard is "clone the repository, run one command". You're building that from
  day one.

**In a company**, the workstation is treated as a controlled asset (see the box further down): the Brewfile is the
small-scale version of the "approved software list" that IT and security keep for every machine.

## Key ideas

| Term | Plain-English meaning |
|---|---|
| **Command Line Tools** | Apple's free kit of basic developer programs: a compiler (`clang`, which turns source code into runnable programs), `make`, `git`, and the system "header" files other software compiles against. Many tools you install later need these. |
| **Compiler** | A program that turns human-written source code into a program the computer can run. `clang` is Apple's. |
| **Package manager** | A program that downloads, installs, updates and removes other programs for you, and keeps track of what's installed. Homebrew is the one most Mac developers use. |
| **Homebrew formula / cask** | A *formula* (`brew "jq"`) is a command-line tool. A *cask* (`cask "orbstack"`) is a normal Mac app with a window. |
| **Brewfile** | A plain text file listing formulas and casks. `brew bundle` installs everything in it. |
| **PATH** | The list of folders your Mac searches, in order, when you type a command name. The first match wins. |
| **Analytics** | Anonymous usage statistics a tool sends back to its makers. |
| **Shell / zsh** | The program inside Terminal that reads your commands. macOS uses zsh. Its settings live in `~/.zprofile` and `~/.zshrc`. |
| **Infrastructure as code** | Defining your environment in version-controlled files instead of setting it up by hand. |

## How to do it

All commands are typed into the macOS Terminal (Cmd + Space, type *Terminal*, Enter). Run them one at a time and
read what each one prints.

### 1 · Install the Command Line Tools

```bash
xcode-select --install
```

A window appears; click **Install** and accept the licence. This installs `clang`, `make`, `git` and the system
headers that Homebrew and many Python packages compile against. The Homebrew installer would ask for these anyway,
but installing them separately makes any failure easier to spot.

Check it worked:

```bash
xcode-select -p                          # should print /Library/Developer/CommandLineTools
```

> **TIP**
> If it says the tools are already installed, that's fine. Run the check command and move on.

### 2 · Install Homebrew, reading the script first

The usual one-line install command downloads a script from the internet and runs it immediately. That works, but
running code you haven't read is exactly the habit you'll teach others to avoid in Project 11, the security lab.
So download it, skim it, then run it:

```bash
curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o /tmp/brew-install.sh
less /tmp/brew-install.sh   # skim: what it creates, where, and what it asks admin (sudo) rights for. Press q to quit.
/bin/bash /tmp/brew-install.sh
```

> **IN PLAIN ENGLISH**
> `curl` downloads a file. `less` lets you scroll through it. `/bin/bash file` runs it. The installer will ask for
> your Mac login password once, because it needs to create a folder outside your home folder.

On Apple Silicon Macs, Homebrew installs into `/opt/homebrew`. That folder isn't on your PATH yet, so your shell
won't find the tools you install. Add it to your login settings:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile   # make it permanent for new terminals
eval "$(/opt/homebrew/bin/brew shellenv)"                          # apply it to this terminal right now
```

The line that ends up in `~/.zprofile` is kept as a reference copy in this repo at
[`bootstrap/home/.zprofile`](../../bootstrap/home/.zprofile).

**Why the "shellenv" line matters (Figure 2 in the guide).** Your Mac searches the folders on your PATH from left
to right and runs the first match:

| | 1st folder searched | 2nd | 3rd | Result of typing `git` |
|---|---|---|---|---|
| **With the shellenv line (correct)** | `/opt/homebrew/bin` → Homebrew's newer git, **found** | `/usr/local/bin` → not checked (already found) | `/usr/bin` → Apple's older git, ignored | You get Homebrew's newer git |
| **Without it (common mistake)** | `/usr/local/bin` → nothing here | `/usr/bin` → Apple's older git, **found** | `/opt/homebrew/bin` → missing, never searched | You silently get Apple's older git |

The line puts Homebrew's folder first. Without it, you silently get Apple's older built-in tools.

### 3 · Turn off analytics

Homebrew sends anonymous usage analytics by default. In a governed environment, you decide what data leaves the
machine, and you make that decision on purpose:

```bash
brew analytics off
brew analytics                              # confirm it says "disabled"
```

### 4 · Create the project folder and the Brewfile

```bash
mkdir -p ~/dev/rag-platform/bootstrap   # -p creates parent folders too, with no error if they exist
cd ~/dev/rag-platform/bootstrap         # "change directory": move into the folder
```

Create a file named `Brewfile` (no extension) in that folder. Start with only the general-purpose tools. Later
steps each add their own section, and every line gets a comment saying why it's there.

File · `~/dev/rag-platform/bootstrap/Brewfile` — committed here as [`bootstrap/Brewfile`](../../bootstrap/Brewfile):

```ruby
# ---- Core CLI (Step 1) ----
brew "git"                  # newer than Apple's bundled git
brew "gh"                   # GitHub CLI: repos, PRs, Actions from the terminal
brew "jq"                   # query/transform JSON (API responses, traces, configs)
brew "yq"                   # same for YAML (Compose, Kubernetes, Helm files)
brew "just"                 # task runner: one-word commands like `just up`, `just test`
brew "direnv"               # loads per-project environment variables when you cd in
brew "wget"                 # downloading models and datasets
brew "tree"                 # inspect folder structures
```

What each tool is for, in plain English:

| Tool | What it does for you |
|---|---|
| `git` | Version control: saves snapshots of your files so you can see every change and undo mistakes. |
| `gh` | Works with GitHub (repositories, pull requests, CI runs) from the Terminal. |
| `jq` | Picks out and reshapes data in JSON, the format most APIs and logs use. |
| `yq` | The same for YAML, the format Docker Compose, Kubernetes and Helm use. |
| `just` | Lets you save long commands as short named shortcuts, e.g. `just up` to start the whole platform. |
| `direnv` | Automatically loads a project's settings when you enter its folder, and unloads them when you leave, like lights that switch on as you walk into a room. |
| `wget` | Downloads files, such as models and datasets. |
| `tree` | Draws a folder and its contents as a tree, so you can see the structure at a glance. |

### 5 · Install everything from the file

```bash
brew bundle --file=Brewfile
brew bundle check --file=Brewfile          # expect: "The Brewfile's dependencies are satisfied."
```

**The Brewfile workflow (Figure 3 in the guide).** The Brewfile is a text file, saved in git. `brew bundle` reads
the list and installs whatever is missing (git, gh, jq, yq, just, direnv, wget, tree). `brew bundle check` then
confirms everything is satisfied. Same file on a new Mac, or a teammate's Mac → the same tools, in minutes. The
loop is always: edit the list, run `brew bundle`, confirm with `brew bundle check`.

### 6 · Switch on direnv

direnv only works once it's connected to your shell:

```bash
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc
source ~/.zshrc                                 # reload settings in this terminal
```

The resulting `~/.zshrc` line is kept as a reference copy at [`bootstrap/home/.zshrc`](../../bootstrap/home/.zshrc).

### 7 · Health check

```bash
brew doctor                                 # goal: "Your system is ready to brew."
which git                                   # should be /opt/homebrew/bin/git, not /usr/bin/git
git --version
```

> **WATCH OUT**
> If `which git` still shows `/usr/bin/git`, the PATH line from part 2 didn't load. Open a new Terminal window, or
> run the `eval` line again.

## Benefits

- **One command rebuilds your whole toolset.** That's also disaster recovery for your workstation.
- **One file describes the whole machine.** Homebrew handles both command-line tools (`brew`) and normal apps
  (`cask`).
- **The Brewfile is readable documentation.** Anyone can see the platform's system dependencies at a glance.
- **Native speed on Apple Silicon.** Homebrew provides native arm64 builds, so nothing runs through the slower
  Rosetta translation layer (Apple's emulator for older Intel-only programs).

## Drawbacks and risks

- **Versions aren't pinned well.** `brew "jq"` installs whatever version is current today. A colleague running the
  same file in six months may get a newer version. Homebrew is "reproducible enough" for a workstation, not
  identical down to the last byte.
- **Upgrades are all-or-nothing.** `brew upgrade` upgrades everything at once. A changed shared library (OpenSSL,
  ICU) can break a compiled Python package. Upgrade on purpose, not casually.
- **You are trusting someone else's software (supply-chain trust).** You rely on Homebrew's maintainers and build
  systems. That's reasonable for a personal developer machine. In a bank's production environment, packages would
  be copied to an internal mirror and scanned first.
- **macOS only.** Your CI machines and servers will run Linux. That's why, from Step 3 on, the services run in
  containers, and the Brewfile only covers the developer's own tools.

## Alternatives

| Tool | What it is, in plain words | Choose it when |
|---|---|---|
| **Homebrew + Brewfile (our choice)** | The standard macOS package manager. | Solo or small-team Mac workstations. The fastest, best-documented path. |
| **Nix** (via nix-darwin, devbox or devenv) | A package manager that records exact versions with fingerprints and isolates every project. | You need exactly the same setup on Mac and Linux, or many projects needing conflicting versions. Very powerful, but hard to learn. |
| **MacPorts** | An older macOS package manager that builds more from source code. | Rarely chosen today; sometimes for specific scientific software. |
| **mise or asdf** | Version managers for programming languages (Python, Node, Go), pinned per project. | Use alongside Homebrew, not instead of it, when you need several language versions. For Python we use uv instead (Step 2). |
| **Dev Containers** (VS Code / GitHub Codespaces) | The whole development environment defined as a container. | Large teams that need identical setups, or companies that forbid local installs. Weak fit here: containers on a Mac can't use the Apple GPU your models need. |
| **MDM-managed fleets** (Jamf, Kandji) | The company's IT department installs software on every Mac remotely. | The enterprise IT standard. Developers then add Homebrew on top. |

## Which approach fits which situation

| Situation | Best choice |
|---|---|
| Personal learning lab or startup | Homebrew + Brewfile: little friction, good-enough reproducibility. |
| Team of 10+ with "works on my machine" problems | Add Dev Containers or Nix for project dependencies; keep Homebrew for personal tools. |
| Regulated enterprise (banking, health, government) | IT manages machines through MDM, packages come from an internal mirror (Artifactory / Nexus), and approved tools are documented. Your Brewfile doubles as the "approved software list" in a security review. |
| CI/CD build machines | Never Homebrew. Use container images with pinned versions (Step 27). |

> **IN A COMPANY**
> You'll often hear "the developer workstation is a controlled asset". IT knows exactly what's installed, packages
> come from approved sources, and changes are reviewed. A commented Brewfile in git is the small-scale version of
> that same control.

## Common mistakes

- **Forgetting the shellenv line**, so Apple's older `/usr/bin/git` silently wins over Homebrew's.
- **Running `brew` with `sudo`** (admin rights). Homebrew refuses, and you should never force it.
- **Installing tools by hand and "meaning to" add them to the Brewfile later.** Edit the Brewfile first, then run
  `brew bundle`.
- **Generating the file with `brew bundle dump`.** That dumps everything installed on the machine, including
  unrelated tools. Write the file by hand, with a comment on every line saying why it's there.

## Done when

- [ ] `xcode-select -p` prints a path
- [ ] `which brew` shows `/opt/homebrew/bin/brew`
- [ ] `brew analytics` shows disabled
- [ ] `brew bundle check --file=~/dev/rag-platform/bootstrap/Brewfile` passes
- [ ] `which git` shows `/opt/homebrew/bin/git`
- [ ] `brew doctor` shows no errors that affect you (warnings about unrelated software are fine)

The `bootstrap/` folder becomes part of the git repository in Step 4, so the Brewfile will be version-controlled
from its very first commit.

## Recap

> **RECAP**
> You installed Apple's developer tools and Homebrew, turned off analytics, and wrote your first
> infrastructure-as-code file: a commented Brewfile that rebuilds your toolset with one command. The habit that
> matters: write it down first, then install.

## What was added to the repo in this step

| File | Purpose |
|---|---|
| [`bootstrap/Brewfile`](../../bootstrap/Brewfile) | The "shopping list" of system tools; `brew bundle --file=bootstrap/Brewfile` installs them. Step 1 adds the Core CLI section (git, gh, jq, yq, just, direnv, wget, tree). |
| [`bootstrap/home/.zprofile`](../../bootstrap/home/.zprofile) | Reference copy of the Homebrew `shellenv` line that goes into `~/.zprofile`, so Homebrew's folder comes first on the PATH. |
| [`bootstrap/home/.zshrc`](../../bootstrap/home/.zshrc) | Reference copy of the `direnv hook zsh` line that goes into `~/.zshrc`, so direnv works in every new terminal. |
| [`docs/steps/step-01-homebrew-brewfile.md`](step-01-homebrew-brewfile.md) | This write-up. |
| [`docs/steps/README.md`](README.md) | Index of all step write-ups (created in this step). |
| [`docs/glossary.md`](../glossary.md) | Project glossary; Step 1 terms added (created in this step). |
| [`CHANGELOG.md`](../../CHANGELOG.md) | Project changelog in Keep a Changelog style (created in this step). |

## Notes for this repository

- The guide places the project at `~/dev/rag-platform/`. In this repository that folder **is** the repo root, so
  `~/dev/rag-platform/bootstrap/Brewfile` is `bootstrap/Brewfile` here. To follow the guide literally on a Mac,
  clone this repo to `~/dev/rag-platform`.
- Parts 2 and 6 of the chapter append lines to files in your home folder (`~/.zprofile`, `~/.zshrc`). Those files
  are not part of the project, so this repo keeps **reference copies** under `bootstrap/home/`, mirroring the path
  under `~`. During workstation setup, append their contents to your real `~/.zprofile` and `~/.zshrc` (or run the
  `echo ... >>` commands above, which do exactly that). Later steps add their own shell lines to the same
  reference files.
- Validation done here (Linux container, no Homebrew): the Brewfile parses as valid Ruby (`ruby -c`), and the
  reference shell snippets pass `bash -n`. `brew bundle`, `brew doctor` and the `which` checks must be run on the
  Mac itself.
