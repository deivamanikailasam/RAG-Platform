#!/usr/bin/env bash
# Step 4: configure git (identity + safe defaults), create the ed25519 SSH key, upload it to GitHub
# for login AND for commit signing, and turn on SSH commit signing.
#
# This is the scripted version of parts 1 and 2 of the Step 4 chapter. Every command is the guide's;
# the script only makes them repeatable (it skips what is already done).
#
# Usage (on macOS, after `just bootstrap` installed git and gh):
#   GIT_NAME="Your Name" GIT_EMAIL="12345678+you@users.noreply.github.com" bash bootstrap/git-setup.sh
#   KEY_TITLE="M5 Max" bash bootstrap/git-setup.sh        # title shown on GitHub for the key
#   SKIP_GITHUB=1 bash bootstrap/git-setup.sh             # local git + key only, no gh calls
#   CHECK_ONLY=1 bash bootstrap/git-setup.sh              # only print the current state
#
# The private key (~/.ssh/id_ed25519, no .pub) never leaves your Mac and is never committed.

set -euo pipefail

KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
KEY_TITLE="${KEY_TITLE:-M5 Max}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

check() {
  say "git global settings"
  git config --global --list | grep -E 'user|init|pull|fetch|autocrlf|gpg|signingkey' || true
  say "SSH key"
  if [[ -f "$KEY.pub" ]]; then cat "$KEY.pub"; else echo "no key at $KEY.pub"; fi
  if [[ "${SKIP_GITHUB:-0}" != "1" ]]; then
    say "GitHub SSH login (expect: Hi <username>! You've successfully authenticated…)"
    ssh -T git@github.com || true   # exits 1 even on success, because GitHub offers no shell
  fi
}

if [[ "${CHECK_ONLY:-0}" == "1" ]]; then check; exit 0; fi

command -v git >/dev/null 2>&1 || fail "git is missing: just bootstrap"

# ---- 1 · Configure git ----
say "1 · Identity and safe defaults"
NAME="${GIT_NAME:-$(git config --global user.name || true)}"
EMAIL="${GIT_EMAIL:-$(git config --global user.email || true)}"
[[ -n "$NAME" && -n "$EMAIL" ]] || fail "set GIT_NAME and GIT_EMAIL (use your GitHub noreply address to keep your email private)"
git config --global user.name "$NAME"
git config --global user.email "$EMAIL"
git config --global init.defaultBranch main     # new repos start on "main"
git config --global pull.ff only                # never create surprise merge commits on pull
git config --global fetch.prune true            # forget branches deleted on the server
git config --global core.autocrlf input         # store LF line endings (Linux-style) in the repo

# ---- 2 · SSH key for GitHub login and commit signing ----
say "2 · ed25519 SSH key"
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
if [[ ! -f "$KEY" ]]; then
  ssh-keygen -t ed25519 -C "$EMAIL" -f "$KEY"   # set a passphrase when asked
fi
if [[ "$(uname -s)" == "Darwin" ]]; then
  ssh-add --apple-use-keychain "$KEY"           # store the passphrase in Keychain
  if ! grep -q '^Host github.com' "$HOME/.ssh/config" 2>/dev/null; then
    grep -v '^#' "$REPO_ROOT/bootstrap/home/.ssh/config" >> "$HOME/.ssh/config"
    chmod 600 "$HOME/.ssh/config"
  fi
fi

if [[ "${SKIP_GITHUB:-0}" != "1" ]]; then
  command -v gh >/dev/null 2>&1 || fail "gh is missing: just bootstrap"
  gh auth status >/dev/null 2>&1 || gh auth login --git-protocol ssh --web
  gh auth refresh -h github.com -s admin:public_key,admin:ssh_signing_key   # permission to add keys
  # Upload twice: once to log in (push), once to verify signatures. Ignore "already exists".
  gh ssh-key add "$KEY.pub" --title "$KEY_TITLE" --type authentication || true
  gh ssh-key add "$KEY.pub" --title "$KEY_TITLE signing" --type signing || true
fi

# ---- Commit signing ----
say "Commit and tag signing with the SSH key"
git config --global gpg.format ssh
git config --global user.signingkey "$KEY.pub"
git config --global commit.gpgsign true
git config --global tag.gpgsign true
SIGNER_LINE="$EMAIL namespaces=\"git\" $(cat "$KEY.pub")"
touch "$HOME/.ssh/allowed_signers"
grep -qxF "$SIGNER_LINE" "$HOME/.ssh/allowed_signers" || echo "$SIGNER_LINE" >> "$HOME/.ssh/allowed_signers"
git config --global gpg.ssh.allowedSignersFile "$HOME/.ssh/allowed_signers"

check
