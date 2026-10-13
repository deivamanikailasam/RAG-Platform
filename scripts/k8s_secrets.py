#!/usr/bin/env python3
"""The only two Kubernetes Secrets the platform needs (Step 29), printed as YAML for kubectl.

    just k8s-pull-secret        ghcr-pull in namespace rag: lets the cluster download your private images
    just k8s-repo-secret        Argo CD's read-only deploy key for the repository

Values come from environment variables (your SOPS env), never from command-line arguments, which
end up in shell history and process lists. Pipe the output straight into `kubectl apply -f -`.
Application secrets (database logins, keys) are NOT Kubernetes Secrets: OpenBao hands them to the pod.
"""

from __future__ import annotations

import base64
import json
import os
import sys

import yaml


class SecretError(Exception):
    pass


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise SecretError(f"{name} is not set (add it to secrets/dev.enc.env)")
    return value


def pull_secret(namespace: str = "rag") -> dict[str, object]:
    user, token = _env("GHCR_USER"), _env("GHCR_READ_TOKEN")
    auth = base64.b64encode(f"{user}:{token}".encode()).decode()
    config = {"auths": {"ghcr.io": {"username": user, "password": token, "auth": auth}}}
    return {
        "apiVersion": "v1", "kind": "Secret", "type": "kubernetes.io/dockerconfigjson",
        "metadata": {"name": "ghcr-pull", "namespace": namespace},
        "stringData": {".dockerconfigjson": json.dumps(config)},
    }  # fmt: skip


def repo_secret(url: str) -> dict[str, object]:
    key = _env("ARGOCD_DEPLOY_KEY")
    if "PRIVATE KEY" not in key:
        raise SecretError("ARGOCD_DEPLOY_KEY doesn't look like an SSH private key")
    if not url.startswith("git@github.com:"):
        raise SecretError(f"expected an SSH repository URL (git@github.com:…), got {url!r}")
    return {
        "apiVersion": "v1", "kind": "Secret",
        "metadata": {"name": "repo-rag-platform", "namespace": "argocd",
                     # this label is how Argo CD finds repository credentials
                     "labels": {"argocd.argoproj.io/secret-type": "repository"}},
        "stringData": {"type": "git", "url": url, "sshPrivateKey": key.rstrip("\n") + "\n"},
    }  # fmt: skip


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["pull-secret"]:
            doc = pull_secret()
        elif argv[:1] == ["repo-secret"] and len(argv) == 2:
            doc = repo_secret(argv[1])
        else:
            print(
                "usage: k8s_secrets.py pull-secret | repo-secret <git@github.com:owner/repo.git>",
                file=sys.stderr,
            )
            return 2
    except SecretError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(yaml.safe_dump(doc, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
