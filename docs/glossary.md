# Glossary

Plain-English definitions of the terms introduced across the build guide, in alphabetical order.
The number in brackets is the step where the term first appears; see [`docs/steps/`](steps/README.md).

| Term | Meaning | Step |
|---|---|---:|
| Analytics | Anonymous usage statistics a tool sends back to its makers. | 1 |
| Brewfile | A plain text file listing Homebrew formulas and casks; `brew bundle` installs everything in it. | 1 |
| Cask | A Homebrew package that is a normal Mac app with a window. | 1 |
| CLI | Command-line interface: a program you control by typing commands. | 1 |
| Command Line Tools | Apple's free kit of basic developer programs: compiler, `make`, `git`, system headers. | 1 |
| Compiler | A program that turns human-written source code into a program the computer can run. | 1 |
| Dependency | A package your project needs in order to work. | 2 |
| Dependency group | A named set of extra dependencies in `pyproject.toml` (PEP 735), e.g. `dev` for test tools not needed in production. | 2 |
| Dev dependency | A package needed only while developing (e.g. pytest), not when the app runs in production. | 2 |
| direnv | A tool that loads a project's settings automatically when you enter its folder. | 1 |
| Drift | When the dependency list (`pyproject.toml`) and the lockfile (`uv.lock`) no longer match; `uv sync --locked` catches it. | 2 |
| Formula | A Homebrew package that is a command-line tool. | 1 |
| Hash | A short fingerprint calculated from a file's contents; change one byte and it changes completely. | 2 |
| Homebrew | The standard package manager ("app store for developer tools") on macOS. | 1 |
| Infrastructure as code | Defining your environment in version-controlled files instead of setting it up by hand. | 1 |
| Interpreter | The `python` program itself: the engine that reads and runs Python code, e.g. CPython 3.12. | 2 |
| Lockfile | A file recording the exact version and hash of every package in the full dependency tree (`uv.lock`). | 2 |
| MDM | Mobile Device Management: how company IT installs and controls software on employees' Macs (e.g. Jamf, Kandji). | 1 |
| Package manager | A program that installs, updates and removes other software and tracks what's installed. | 1 |
| PATH | The ordered list of folders your shell searches when you type a command. First match wins. | 1 |
| PEP | Python Enhancement Proposal: an official Python standard (e.g. PEP 621 `pyproject.toml`, PEP 735 dependency groups, PEP 668 protected system Pythons). | 2 |
| pyproject.toml | The standard Python project file listing the dependency ranges you'll accept (PEP 621). | 2 |
| Shell / zsh | The program inside Terminal that reads and runs your commands; zsh is the macOS default. | 1 |
| Transitive dependency | A dependency of a dependency: a package you never chose that comes along because one you chose needs it. | 2 |
| uv | Astral's all-in-one Python tool: interpreters, virtual environments, locking and tool installs. | 2 |
| Virtual environment | A private folder of packages (`.venv`) for one project, tied to one interpreter. | 2 |
| Wheel | A pre-built Python package, ready to install, like flat-pack furniture. | 2 |
