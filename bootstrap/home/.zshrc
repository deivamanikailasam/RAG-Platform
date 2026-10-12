# Reference copy of the lines this project adds to ~/.zshrc (interactive shell settings).
# Copy or append these to ~/.zshrc during workstation setup; do not source this file from the repo.

# ---- direnv (Step 1) ----
# Connects direnv to zsh so a project's .envrc loads when you cd in and unloads when you leave.
eval "$(direnv hook zsh)"

# ---- SOPS age key location (Step 6) ----
# SOPS looks for the age private key in different default places on different systems; tell it exactly.
# (The project's .envrc sets the same variable inside the repo via direnv.)
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
