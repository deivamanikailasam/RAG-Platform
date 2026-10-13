# Reference copy of the lines this project adds to ~/.zprofile (login shell settings).
# Copy or append these to ~/.zprofile during workstation setup; do not source this file from the repo.

# ---- Homebrew (Step 1) ----
# Puts /opt/homebrew/bin first on your PATH so Homebrew's tools (e.g. its newer git)
# win over Apple's older built-in ones in /usr/bin.
eval "$(/opt/homebrew/bin/brew shellenv)"
