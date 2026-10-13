"""The Kubernetes manifests (Step 29): rendered by the real kustomize, then sent to a real API
server, so schemas, Pod Security and our admission policies are checked exactly as in a cluster.

Needs kubectl, kube-apiserver and etcd on PATH (just tools kubectl kube-apiserver etcd). Skips
otherwise.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from .kube import ApiServer, available

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
ZERO = "0" * 64
KUSTOMIZATIONS = ["cluster", "base/rag-api", "envs/local", "argocd/install", "argocd/apps"]
DIGEST = re.compile(r"^(ghcr\.io/owner/|quay\.io/(openbao|argoproj)/|ghcr\.io/dexidp/|public\.ecr\.aws/)"
                    r"[a-z0-9._/-]+@sha256:[a-f0-9]{64}$")  # fmt: skip


def _load_setup() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "vault_setup_k8s", ROOT / "scripts/vault_setup.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["vault_setup_k8s"] = module
    spec.loader.exec_module(module)
    return module


def render(path: str) -> list[dict[str, Any]]:
    """`kubectl kustomize`, with the <digest> placeholders filled in (as you do before applying)."""
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not installed (just tools kubectl)")
    out = subprocess.run(["kubectl", "kustomize", str(DEPLOY / path)],  # noqa: S603, S607
                         capture_output=True, text=True, check=True).stdout  # fmt: skip
    return [d for d in yaml.safe_load_all(out.replace("<digest>", ZERO)) if d]


def dump(docs: list[dict[str, Any]]) -> str:
    return yaml.safe_dump_all(docs, sort_keys=False)


def pod_specs(docs: list[dict[str, Any]]) -> Iterator[tuple[str, dict[str, Any]]]:
    for d in docs:
        if d["kind"] in ("Deployment", "StatefulSet", "DaemonSet", "Job"):
            yield d["metadata"]["name"], d["spec"]["template"]["spec"]


def containers(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return list(spec.get("containers", [])) + list(spec.get("initContainers", []))


# ---- static checks on what kustomize renders ------------------------------------------------------


@pytest.mark.parametrize("path", KUSTOMIZATIONS)
def test_every_kustomization_renders(path: str) -> None:
    assert render(path)


def test_rag_api_workload_is_hardened() -> None:
    docs = render("envs/local")
    ((name, spec),) = list(pod_specs(docs))
    assert name == "rag-api"
    assert spec["automountServiceAccountToken"] is False
    assert spec["securityContext"]["runAsNonRoot"] is True
    for c in containers(spec):
        assert DIGEST.match(c["image"]), c["image"]
        sc = c["securityContext"]
        assert sc["readOnlyRootFilesystem"] is True
        assert sc["allowPrivilegeEscalation"] is False
        assert sc["capabilities"]["drop"] == ["ALL"]
        assert "memory" in c["resources"]["limits"]
        assert c["resources"]["requests"]
    deploy = next(d for d in docs if d["kind"] == "Deployment")
    assert deploy["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
    assert any(d["kind"] == "PodDisruptionBudget" for d in docs)
    assert {d["metadata"]["name"] for d in docs if d["kind"] == "NetworkPolicy"} == {
        "rag-api",
        "default-deny",
    }


def test_agent_sidecar_matches_openbao_role() -> None:
    """The pod, its agent config and OpenBao's role must agree, or the login fails at 3 a.m."""
    vs = _load_setup()
    docs = render("envs/local")
    ((_, spec),) = list(pod_specs(docs))
    (agent,) = spec["initContainers"]
    assert agent["restartPolicy"] == "Always"  # a native sidecar: starts first, keeps running
    token = next(v for v in spec["volumes"] if v["name"] == "openbao-token")
    source = token["projected"]["sources"][0]["serviceAccountToken"]
    assert source["audience"] == vs.K8S_AUDIENCE
    assert source["expirationSeconds"] <= 3600
    (role,) = vs.K8S_ROLES
    sa = next(d for d in docs if d["kind"] == "ServiceAccount")
    assert (sa["metadata"]["name"], sa["metadata"]["namespace"]) == (
        role.service_account,
        role.namespace,
    )
    assert spec["serviceAccountName"] == role.service_account
    cfg = next(d for d in docs if d["kind"] == "ConfigMap")["data"]["agent.hcl"]
    mount = next(m for m in agent["volumeMounts"] if m["name"] == "openbao-token")["mountPath"]
    assert f'path = "{mount}/{source["path"]}"' in cfg
    assert f'role = "{role.name}"' in cfg
    assert f'mount_path = "auth/{vs.K8S_MOUNT}"' in cfg
    assert "remove_jwt_after_reading = false" in cfg


def test_compose_and_kubernetes_agents_write_the_same_files() -> None:
    compose = (ROOT / "infra/config/openbao/agent-rag-api.hcl").read_text()
    k8s = (DEPLOY / "base/rag-api/openbao-agent.hcl").read_text()
    pattern = re.compile(r'destination\s*=\s*"([^"]+)"')
    assert pattern.findall(compose) == pattern.findall(k8s)
    templates = re.compile(r"contents\s*=\s*(\".*\")")
    assert templates.findall(compose) == templates.findall(k8s)


def test_argocd_projects_keep_the_app_inside_its_namespace() -> None:
    docs = render("argocd/apps")
    projects = {d["metadata"]["name"]: d["spec"] for d in docs if d["kind"] == "AppProject"}
    assert projects["rag"]["destinations"] == [
        {"server": "https://kubernetes.default.svc", "namespace": "rag"}
    ]
    assert projects["rag"]["clusterResourceWhitelist"] == []
    apps = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Application"}
    repos = {p["sourceRepos"][0] for p in projects.values()} | {
        a["spec"]["source"]["repoURL"] for a in apps.values()
    }
    assert len(repos) == 1  # one repository is the single source of truth
    for name, app in apps.items():
        assert app["spec"]["source"]["targetRevision"] == "main"
        path = app["spec"]["source"]["path"]
        assert render(path.removeprefix("deploy/")), f"{name}: {path} doesn't render"
        assert app["spec"]["syncPolicy"]["automated"]["selfHeal"] is True
    assert apps["rag-api-local"]["spec"]["project"] == "rag"
    assert (
        apps["cluster"]["spec"]["syncPolicy"]["automated"]["prune"] is False
    )  # never auto-delete a namespace
    waves = {
        n: int(a["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"])
        for n, a in apps.items()
    }
    assert waves["cluster"] < waves["rag-api-local"]


def test_vendored_argocd_matches_its_recorded_hash() -> None:
    import hashlib

    kustomization = (DEPLOY / "argocd/install/kustomization.yaml").read_text()
    recorded = re.search(r"sha256 ([0-9a-f]{64})", kustomization)
    assert recorded is not None
    actual = hashlib.sha256(
        (DEPLOY / "argocd/install/upstream/install.yaml").read_bytes()
    ).hexdigest()
    assert actual == recorded.group(1)


# ---- against a real API server -------------------------------------------------------------------


def _wait_until_policies_enforce(api: ApiServer) -> None:
    """New admission policies take a moment to load (the API server refreshes them every second
    or so). Like any cluster: wait until a known-bad object is refused before relying on them."""
    import time

    api.kubectl("create", "serviceaccount", "default", "-n", "rag", check=False)
    canary = {"apiVersion": "apps/v1", "kind": "Deployment",
              "metadata": {"name": "canary", "namespace": "rag"},
              "spec": {"selector": {"matchLabels": {"a": "b"}},
                       "template": {"metadata": {"labels": {"a": "b"}},
                                    "spec": {"containers": [{"name": "c", "image": "busybox"}]}}}}  # fmt: skip
    for _ in range(60):
        r = api.kubectl(
            "create", "--dry-run=server", "-f", "-", stdin=json.dumps(canary), check=False
        )
        if "rag-images-pinned" in r.stderr or "rag-workloads-hardened" in r.stderr:
            return
        time.sleep(0.5)
    pytest.fail("admission policies never became active")


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ApiServer]:
    if not available():
        pytest.skip(
            "kube-apiserver/etcd/kubectl not installed (just tools kube-apiserver etcd kubectl)"
        )
    server = ApiServer(tmp_path_factory.mktemp("kube")).start()
    try:
        server.apply(dump(render("cluster")))
        _wait_until_policies_enforce(server)
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="module")
def deployed(api: ApiServer) -> dict[str, Any]:
    api.apply(dump(render("envs/local")))
    return dict(api.get("deployment", "rag-api", "-n", "rag"))


def pod_from(deployment: dict[str, Any], name: str = "probe", **changes: Any) -> dict[str, Any]:
    """A Pod exactly as the ReplicaSet controller would create it from the Deployment."""
    spec = copy.deepcopy(deployment["spec"]["template"]["spec"])
    for key, value in changes.items():
        if value is None:
            spec.pop(key, None)
        else:
            spec[key] = value
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": "rag"},
        "spec": spec,
    }


def fresh_copy(obj: dict[str, Any]) -> dict[str, Any]:
    """The object as you'd write it: without what the API server added when storing it."""
    new = copy.deepcopy(obj)
    for k in ("resourceVersion", "uid", "creationTimestamp", "generation", "managedFields"):
        new["metadata"].pop(k, None)
    new.pop("status", None)
    return new


def create(api: ApiServer, obj: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return api.kubectl("create", "-f", "-", stdin=json.dumps(obj), check=False)


def test_rag_api_is_accepted_by_every_policy(api: ApiServer, deployed: dict[str, Any]) -> None:
    assert deployed["metadata"]["namespace"] == "rag"
    r = create(api, pod_from(deployed))
    assert r.returncode == 0, r.stderr
    assert "Warning" not in r.stderr  # Pod Security "restricted" has nothing to warn about either


def test_a_tag_instead_of_a_digest_is_refused(api: ApiServer, deployed: dict[str, Any]) -> None:
    spec = deployed["spec"]["template"]["spec"]
    c = copy.deepcopy(spec["containers"])
    c[0]["image"] = "ghcr.io/owner/rag-platform/rag-api:latest"
    r = create(api, pod_from(deployed, "tagged", containers=c))
    assert r.returncode != 0
    assert "rag-images-pinned" in r.stderr
    assert "ghcr.io/owner/rag-platform/rag-api:latest" in r.stderr  # the message names the culprit


@pytest.mark.parametrize(
    "image",
    [f"docker.io/library/python@sha256:{ZERO}", f"ghcr.io/someone-else/rag-api@sha256:{ZERO}"],
)
def test_other_registries_are_refused_even_with_a_digest(
    api: ApiServer, deployed: dict[str, Any], image: str
) -> None:
    c = copy.deepcopy(deployed["spec"]["template"]["spec"]["containers"])
    c[0]["image"] = image
    r = create(api, pod_from(deployed, "elsewhere", containers=c))
    assert r.returncode != 0
    assert "rag-images-pinned" in r.stderr


def test_a_deployment_is_refused_before_any_pod_exists(
    api: ApiServer, deployed: dict[str, Any]
) -> None:
    bad = fresh_copy(deployed)
    bad["metadata"]["name"] = "rag-api-tagged"
    bad["spec"]["template"]["spec"]["containers"][0]["image"] = "rag-api:dev"
    r = create(api, bad)
    assert r.returncode != 0
    assert "rag-images-pinned" in r.stderr


@pytest.mark.parametrize(
    ("what", "change", "expected"),
    [
        ("root user", {"securityContext": {"runAsUser": 0, "seccompProfile": {"type": "RuntimeDefault"}}},
         "violates PodSecurity"),
        ("writable root filesystem", "writable", "rag-workloads-hardened"),
        ("automatic API token", {"automountServiceAccountToken": None}, "rag-workloads-hardened"),
        ("privileged container", "privileged", "violates PodSecurity"),
    ],
)  # fmt: skip
def test_unsafe_pods_are_refused(api: ApiServer, deployed: dict[str, Any], what: str, change: Any,
                                 expected: str) -> None:  # fmt: skip
    spec = deployed["spec"]["template"]["spec"]
    c = copy.deepcopy(spec["containers"])
    changes: dict[str, Any] = {}
    if change == "writable":
        c[0]["securityContext"]["readOnlyRootFilesystem"] = False
        changes["containers"] = c
    elif change == "privileged":
        c[0]["securityContext"].update(privileged=True, allowPrivilegeEscalation=True)
        changes["containers"] = c
    else:
        changes = change
    r = create(api, pod_from(deployed, what.replace(" ", "-").lower(), **changes))
    assert r.returncode != 0, f"{what} was accepted"
    assert expected in r.stderr


def test_a_forgotten_memory_limit(api: ApiServer, deployed: dict[str, Any]) -> None:
    """The Deployment is refused outright; a bare Pod gets the LimitRange default instead."""
    bad = fresh_copy(deployed)
    bad["metadata"]["name"] = "rag-api-unlimited"
    bad["spec"]["template"]["spec"]["containers"][0]["resources"].pop("limits")
    r = create(api, bad)
    assert r.returncode != 0
    assert "every container needs resource requests and a memory limit" in r.stderr
    c = copy.deepcopy(deployed["spec"]["template"]["spec"]["containers"])
    c[0]["resources"].pop("limits")
    assert create(api, pod_from(deployed, "defaulted", containers=c)).returncode == 0
    pod = api.get("pod", "defaulted", "-n", "rag")
    assert (
        pod["spec"]["containers"][0]["resources"]["limits"]["memory"] == "256Mi"
    )  # from the LimitRange


def test_policies_only_apply_where_enforced(api: ApiServer) -> None:
    api.kubectl("create", "namespace", "sandbox")
    api.kubectl("create", "serviceaccount", "default", "-n", "sandbox", check=False)
    pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "scratch", "namespace": "sandbox"},
           "spec": {"containers": [{"name": "c", "image": "python:3.12"}]}}  # fmt: skip
    assert create(api, pod).returncode == 0


def test_argocd_installs_and_accepts_our_applications(api: ApiServer) -> None:
    api.apply(dump(render("argocd/install")), "--force-conflicts")
    api.kubectl("wait", "--for=condition=Established", "crd/applications.argoproj.io",
                "crd/appprojects.argoproj.io", "--timeout=60s")  # fmt: skip
    api.apply(dump(render("argocd/apps")))
    root = yaml.safe_load((DEPLOY / "argocd/root.yaml").read_text())
    api.apply(dump([root]))
    apps = api.get("applications", "-n", "argocd")["items"]
    assert sorted(a["metadata"]["name"] for a in apps) == [
        "argocd",
        "cluster",
        "rag-api-local",
        "root",
    ]
    projects = api.get("appprojects", "-n", "argocd")["items"]
    assert sorted(p["metadata"]["name"] for p in projects) == ["platform", "rag"]
    # an Application with a typo in its spec is refused by the CRD's schema, not discovered later
    bad = {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
           "metadata": {"name": "typo", "namespace": "argocd"},
           "spec": {"project": "rag", "destination": {"namespace": "rag"},
                    "source": {"repoURL": "x", "path": "y"}, "syncPolicy": {"automated": {"prune": "yes"}}}}  # fmt: skip
    r = create(api, bad)
    assert r.returncode != 0
    assert "prune" in r.stderr
