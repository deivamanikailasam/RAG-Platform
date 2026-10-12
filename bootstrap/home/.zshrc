# Reference copy of the lines this project adds to ~/.zshrc (interactive shell settings).
# Copy or append these to ~/.zshrc during workstation setup; do not source this file from the repo.

# ---- direnv (Step 1) ----
# Connects direnv to zsh so a project's .envrc loads when you cd in and unloads when you leave.
eval "$(direnv hook zsh)"
