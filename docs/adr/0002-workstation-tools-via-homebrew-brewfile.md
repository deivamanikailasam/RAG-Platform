# ADR-0002: Manage workstation tools with Homebrew and a Brewfile

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** deivamanikailasam

## Context
Development happens on a macOS (Apple Silicon) workstation. System tools must be installable
in one command, reviewable, and rebuildable after a hardware failure.

## Decision
We will install system tools with Homebrew and declare every one, with a comment explaining why,
in bootstrap/Brewfile. Tools are added to the Brewfile before installing. Analytics are off.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Nix (nix-darwin/devbox) | Exact, cross-platform reproducibility | Steep learning curve | Overkill for one workstation |
| Dev Containers | Identical team environments | No Apple GPU access in containers | Models need Metal (see ADR-0004) |
| Manual installs | No setup | Not reproducible or auditable | Fails the core requirement |

## Consequences
+ `just bootstrap` rebuilds the toolset; the Brewfile doubles as an approved-software list.
- Versions are not pinned exactly; upgrades must be deliberate (`brew upgrade <tool>`).
- macOS only; CI and servers use pinned container images instead (Step 27).

## Revisit when
The team grows beyond a few developers or needs identical Linux and macOS environments.
