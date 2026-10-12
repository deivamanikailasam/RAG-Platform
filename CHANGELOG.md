# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Step 1: `bootstrap/Brewfile` with the Core CLI tools (git, gh, jq, yq, just, direnv, wget, tree), reference shell snippets for Homebrew's PATH and the direnv hook under `bootstrap/home/`, and the step write-up.
- Step 2: `uv` added to the Brewfile, reference global uv config (`bootstrap/home/.config/uv/uv.toml`: only-managed interpreters, manual downloads, commented company mirror), the `bootstrap/labs/uv-lab.sh` lab replay script, and the step write-up.
- Step 3: OrbStack and dive added to the Brewfile, reference Docker engine config with log rotation (`bootstrap/home/.orbstack/config/docker.json`), `bootstrap/orbstack-setup.sh` (VM cap 24 GB / 8 CPUs), the `bootstrap/labs/container-lab.sh` lab replay script, `bootstrap/NOTES-step3.md` decisions (models native, services in containers), and the step write-up.
