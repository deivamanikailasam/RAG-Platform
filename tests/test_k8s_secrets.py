"""The only two Kubernetes Secrets (Step 29): right shape, right labels, and refusals that never
print the value they refused."""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = "git@github.com:owner/rag-platform.git"
# Not a real key: just the shape the script checks for (the header is split so no scanner trips)
FAKE_KEY = (
    "-----BEGIN OPENSSH "
    + "PRIVATE KEY-----\nnot-a-real-key\n-----END OPENSSH "
    + "PRIVATE KEY-----"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("k8s_secrets", ROOT / "scripts/k8s_secrets.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["k8s_secrets"] = module
    spec.loader.exec_module(module)
    return module


ks = _load()


def test_pull_secret(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("GHCR_USER", "owner")
    monkeypatch.setenv("GHCR_READ_TOKEN", "read-only-token")
    assert ks.main(["pull-secret"]) == 0
    doc = yaml.safe_load(capsys.readouterr().out)
    assert doc["type"] == "kubernetes.io/dockerconfigjson"
    assert doc["metadata"] == {"name": "ghcr-pull", "namespace": "rag"}  # what the overlay names
    auths = json.loads(doc["stringData"][".dockerconfigjson"])["auths"]
    assert list(auths) == ["ghcr.io"]  # only our registry
    assert base64.b64decode(auths["ghcr.io"]["auth"]).decode() == "owner:read-only-token"


def test_repo_secret(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("ARGOCD_DEPLOY_KEY", FAKE_KEY)
    assert ks.main(["repo-secret", REPO]) == 0
    doc = yaml.safe_load(capsys.readouterr().out)
    assert doc["metadata"]["namespace"] == "argocd"
    assert doc["metadata"]["labels"] == {"argocd.argoproj.io/secret-type": "repository"}
    assert doc["stringData"]["url"] == REPO
    assert doc["stringData"]["sshPrivateKey"].endswith("KEY-----\n")  # one trailing newline
    # the URL Argo CD gets matches the one every Application and project uses
    apps = yaml.safe_load((ROOT / "deploy/argocd/root.yaml").read_text())
    assert apps["spec"]["source"]["repoURL"] == REPO


@pytest.mark.parametrize(
    ("env", "call", "message"),
    [
        ({"GHCR_READ_TOKEN": "tok-secret-1"}, lambda: ks.pull_secret(), "GHCR_USER is not set"),
        ({"ARGOCD_DEPLOY_KEY": "tok-secret-2"}, lambda: ks.repo_secret(REPO), "doesn't look like"),
        ({"ARGOCD_DEPLOY_KEY": FAKE_KEY + "tok-secret-3"},
         lambda: ks.repo_secret("https://github.com/owner/rag-platform"), "SSH repository URL"),
    ],
)  # fmt: skip
def test_refusals_never_print_the_value(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], call: Callable[[], Any], message: str
) -> None:
    for name in ("GHCR_USER", "GHCR_READ_TOKEN", "ARGOCD_DEPLOY_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ks.SecretError, match=message) as e:
        call()
    assert "tok-secret" not in str(e.value)
