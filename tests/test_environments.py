"""Staging and production (Step 37): rendered by the real kustomize and sent to a real API server
with the operators' CRDs installed (Argo Rollouts, CloudNativePG, Barman Cloud), so every Rollout,
AnalysisTemplate, Cluster and backup object is checked against the schema the operator will use,
and every pod template against Pod Security and our admission policies."""

from __future__ import annotations

import copy
import hashlib
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
from .test_k8s import DEPLOY, ROOT, ZERO, create, dump, render

ENVS = ["staging", "prod"]
PINNED = re.compile(r"^(ghcr\.io/owner/|quay\.io/openbao/)[a-z0-9._/-]+@sha256:[a-f0-9]{64}$")


def pod_templates(docs: list[dict[str, Any]]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every pod spec, wherever it sits: Deployments, CronJobs and the analysis Job."""
    for d in docs:
        if d["kind"] == "Deployment":
            yield d["metadata"]["name"], d["spec"]["template"]["spec"]
        elif d["kind"] == "CronJob":
            yield d["metadata"]["name"], d["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        elif d["kind"] == "AnalysisTemplate":
            for m in d["spec"]["metrics"]:
                if "job" in m["provider"]:
                    yield f"analysis/{m['name']}", m["provider"]["job"]["spec"]["template"]["spec"]


def by(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    return next(d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name)


# ---- static checks ---------------------------------------------------------------------------------


@pytest.mark.parametrize("env", ENVS)
def test_every_pod_is_pinned_hardened_and_uses_the_production_profile(env: str) -> None:
    docs = render(f"envs/{env}")
    seen = set()
    for name, spec in pod_templates(docs):
        seen.add(name)
        assert spec["automountServiceAccountToken"] is False, name
        for c in spec["containers"] + spec.get("initContainers", []):
            assert PINNED.match(c["image"]), f"{name}: {c['image']}"
            assert c["securityContext"]["readOnlyRootFilesystem"] is True, name
            assert "memory" in c["resources"]["limits"], name
        main = spec["containers"][0]
        profile = {e["name"]: e.get("value") for e in main.get("env", [])}
        if name == "rag-api":
            assert profile["RAG_API_RAG_PROFILE"] == "production"
        elif not name.startswith("analysis/"):
            assert profile["RAG_PROFILE"] == "production", name
    assert seen == {
        "rag-api",
        "rag-ingest",
        "rag-retention",
        "rag-online-eval",
        "analysis/online-eval",
    }


@pytest.mark.parametrize("env", ENVS)
def test_the_worker_has_its_own_identity(env: str) -> None:
    vs = _load("vault_setup")
    docs = render(f"envs/{env}")
    specs = dict(pod_templates(docs))
    assert specs["rag-api"]["serviceAccountName"] == "rag-api"
    for name in ("rag-ingest", "rag-retention", "rag-online-eval", "analysis/online-eval"):
        assert specs[name]["serviceAccountName"] == "rag-ingest", name
    roles = {r.service_account: r for r in vs.K8S_ROLES}
    assert roles["rag-ingest"].policies == ("rag-ingest",)
    agent = next(
        d
        for d in docs
        if d["kind"] == "ConfigMap" and d["metadata"]["name"].startswith("rag-ingest-openbao")
    )
    hcl = agent["data"]["agent.hcl"]
    assert 'role = "rag-ingest"' in hcl
    assert "secret/data/rag-api" not in hcl
    assert "database/creds/rag-api" not in hcl
    policy = (ROOT / "infra/config/openbao/policies/rag-ingest.hcl").read_text()
    asked = re.findall(r'secret \\"([^\\]+)\\"', hcl)
    assert len(asked) == 6  # its db lease, four secret files, the audit reader lease
    for path in asked:
        assert f'path "{path}"' in policy, (
            f"the agent asks for {path} but the policy doesn't allow it"
        )


@pytest.mark.parametrize("env", ENVS)
def test_releases_are_canaries_with_analysis(env: str) -> None:
    docs = render(f"envs/{env}")
    deploy = by(docs, "Deployment", "rag-api")
    rollout = by(docs, "Rollout", "rag-api")
    assert deploy["spec"]["replicas"] == 0  # the Rollout runs the pods
    assert rollout["spec"]["workloadRef"]["name"] == "rag-api"
    labels = deploy["spec"]["template"]["metadata"]["labels"]
    assert all(labels[k] == v for k, v in rollout["spec"]["selector"]["matchLabels"].items())
    canary = rollout["spec"]["strategy"]["canary"]
    assert canary["steps"][0] == {"setWeight": 10}
    assert canary["steps"][-1] == {"setWeight": 100}
    assert canary["analysis"]["templates"] == [{"templateName": "rag-api-canary"}]
    assert (
        by(docs, "HorizontalPodAutoscaler", "rag-api")["spec"]["scaleTargetRef"]["kind"]
        == "Rollout"
    )
    env_vars = {e["name"]: e for e in deploy["spec"]["template"]["spec"]["containers"][0]["env"]}
    names = list(env_vars)
    # $(VAR) only works for variables defined EARLIER in the list
    assert names.index("RAG_API_RELEASE") < names.index("OTEL_RESOURCE_ATTRIBUTES")
    assert names.index("RAG_ENVIRONMENT") < names.index("OTEL_RESOURCE_ATTRIBUTES")
    assert env_vars["RAG_ENVIRONMENT"]["value"] == env
    # the identity provider is on HTTPS in real environments: rag-api must be allowed to reach it
    egress_ports = {
        p["port"]
        for rule in by(docs, "NetworkPolicy", "rag-api")["spec"]["egress"]
        for p in rule["ports"]
    }
    assert env_vars["RAG_API_OIDC_JWKS_URL"]["value"].startswith("https://")
    assert 443 in egress_ports
    insufficient = by(docs, "AnalysisTemplate", "rag-api-canary")["spec"]["args"][3]
    assert insufficient == {
        "name": "on-insufficient",
        "value": "pass" if env == "staging" else "fail",
    }


def test_prod_spreads_over_zones_and_keeps_capacity() -> None:
    docs = render("envs/prod")
    hpa = by(docs, "HorizontalPodAutoscaler", "rag-api")["spec"]
    assert hpa["minReplicas"] >= 3
    spread = by(docs, "Deployment", "rag-api")["spec"]["template"]["spec"][
        "topologySpreadConstraints"
    ]
    zone = next(s for s in spread if s["topologyKey"] == "topology.kubernetes.io/zone")
    assert zone["whenUnsatisfiable"] == "DoNotSchedule"
    assert by(docs, "PodDisruptionBudget", "rag-api")["spec"] == {
        "maxUnavailable": 1,
        "selector": {
            "matchLabels": {
                "app.kubernetes.io/name": "rag-api",
                "app.kubernetes.io/part-of": "rag-platform",
            }
        },
    }


def test_prod_database_is_ha_with_point_in_time_recovery() -> None:
    docs = render("data/envs/prod")
    spec = by(docs, "Cluster", "rag-db")["spec"]
    assert spec["instances"] == 3
    assert spec["postgresql"]["synchronous"] == {
        "method": "any",
        "number": 1,
        "dataDurability": "required",
    }
    assert spec["affinity"]["podAntiAffinityType"] == "required"
    assert spec["affinity"]["topologyKey"] == "topology.kubernetes.io/zone"
    assert spec["plugins"][0]["isWALArchiver"] is True
    store = by(docs, "ObjectStore", spec["plugins"][0]["parameters"]["barmanObjectName"])
    assert store["spec"]["retentionPolicy"] == "30d"
    assert by(docs, "ScheduledBackup", "rag-db-nightly")["spec"]["cluster"] == {"name": "rag-db"}
    staging = by(render("data/envs/staging"), "Cluster", "rag-db")["spec"]
    assert staging["instances"] == 2


@pytest.mark.parametrize(("folder", "file"), [("argo-rollouts/install", "upstream/install.yaml"),
                                              ("cnpg/install", "upstream/cnpg.yaml"),
                                              ("cnpg/install", "upstream/barman-cloud.yaml")])  # fmt: skip
def test_vendored_operators_match_their_recorded_hash(folder: str, file: str) -> None:
    kustomization = (DEPLOY / folder / "kustomization.yaml").read_text()
    line = next(x for x in kustomization.splitlines() if file in x)
    recorded = re.search(r"sha256 ([0-9a-f]{64})", line)
    assert recorded is not None, line
    assert hashlib.sha256((DEPLOY / folder / file).read_bytes()).hexdigest() == recorded.group(1)


def test_analysis_queries_are_valid_promql(tmp_path: Path) -> None:
    """Each Prometheus query, with its arguments filled in, must parse: a typo would otherwise
    only show up as a failed (or worse, always-passing) canary."""
    if shutil.which("promtool") is None:
        pytest.skip("promtool not installed (just tools promtool)")
    template = by(render("envs/prod"), "AnalysisTemplate", "rag-api-canary")
    rules = []
    for m in template["spec"]["metrics"]:
        if "prometheus" in m["provider"]:
            q = m["provider"]["prometheus"]["query"]
            q = q.replace("{{args.canary}}", "abc123").replace("{{args.stable}}", "def456")
            assert "{{" not in q, m["name"]
            rules.append({"record": f"canary:{m['name'].replace('-', '_')}", "expr": q})
    assert len(rules) == 5
    path = tmp_path / "analysis.yml"
    path.write_text(yaml.safe_dump({"groups": [{"name": "analysis", "rules": rules}]}))
    r = subprocess.run(["promtool", "check", "rules", str(path)], capture_output=True, text=True)  # noqa: S603, S607
    assert r.returncode == 0, r.stdout + r.stderr


def test_alert_rules_and_their_tests_pass() -> None:
    if shutil.which("promtool") is None:
        pytest.skip("promtool not installed (just tools promtool)")
    folder = ROOT / "infra/config/prometheus"
    for args in (["check", "rules", *sorted(str(p) for p in (folder / "rules").glob("*.yml"))],
                 ["test", "rules", "tests/rules_test.yml", "tests/rag_answers_test.yml"]):  # fmt: skip
        r = subprocess.run(["promtool", *args], cwd=folder, capture_output=True, text=True)  # noqa: S603, S607
        assert r.returncode == 0, r.stdout + r.stderr


def test_dr_drill_renders_a_point_in_time_restore() -> None:
    drill = _load("dr_drill")
    doc = drill.render("2026-10-13 18:59:00+10:00")
    assert doc["spec"]["bootstrap"]["recovery"]["recoveryTarget"] == {
        "targetTime": "2026-10-13 08:59:00+00"
    }
    assert doc["metadata"]["name"] != "rag-db"  # never over production
    assert "recoveryTarget" not in drill.render(None)["spec"]["bootstrap"]["recovery"]
    with pytest.raises(ValueError, match="offset"):
        drill.render("2026-10-13 08:59:00")


@pytest.mark.parametrize("env", ENVS)
def test_argocd_apps_render_and_stay_inside_their_projects(env: str) -> None:
    """Each environment's Argo CD: every app's path renders, and its project allows where it goes
    and every kind it creates (Argo CD would refuse to sync otherwise, at 3 a.m.)."""
    docs = render(f"argocd/envs/{env}")
    projects = {d["metadata"]["name"]: d["spec"] for d in docs if d["kind"] == "AppProject"}
    apps = {d["metadata"]["name"]: d["spec"] for d in docs if d["kind"] == "Application"}
    assert set(apps) == {
        "argocd",
        "cluster",
        "argo-rollouts",
        "cnpg",
        f"rag-data-{env}",
        f"rag-api-{env}",
    }
    assert (
        apps[f"rag-data-{env}"]["syncPolicy"]["automated"]["prune"] is False
    )  # never auto-delete a database
    for name, app in apps.items():
        project = projects[app["project"]]
        allowed = {d["namespace"] for d in project["destinations"]}
        assert app["destination"]["namespace"] in allowed, name
        rendered = render(app["source"]["path"].removeprefix("deploy/"))
        cluster_kinds = {
            (w["group"], w["kind"]) for w in project.get("clusterResourceWhitelist", [])
        }
        only = project.get("namespaceResourceWhitelist")
        for d in rendered:
            group = d["apiVersion"].split("/")[0] if "/" in d["apiVersion"] else ""
            namespaced = d["kind"] not in ("Namespace", "CustomResourceDefinition", "ClusterRole",
                                           "ClusterRoleBinding", "MutatingWebhookConfiguration",
                                           "ValidatingWebhookConfiguration", "ValidatingAdmissionPolicy",
                                           "ValidatingAdmissionPolicyBinding")  # fmt: skip
            if not namespaced:
                assert (group, d["kind"]) in cluster_kinds, (
                    f"{name}: project {app['project']} can't create {d['kind']}"
                )
            elif only is not None:
                assert {"group": group, "kind": d["kind"]} in only, (
                    f"{name}: {d['kind']} not whitelisted"
                )
            ns = d["metadata"].get("namespace")
            if namespaced and ns:
                assert ns in allowed, f"{name}: {d['kind']} in {ns}"


# ---- against a real API server with the operators' CRDs ------------------------------------------


def _crds(path: str) -> list[dict[str, Any]]:
    return [d for d in render(path) if d["kind"] == "CustomResourceDefinition"]


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ApiServer]:
    if not available():
        pytest.skip(
            "kube-apiserver/etcd/kubectl not installed (just tools kube-apiserver etcd kubectl)"
        )
    from .test_k8s import _wait_until_policies_enforce

    server = ApiServer(tmp_path_factory.mktemp("kube-envs")).start()
    try:
        server.apply(dump(render("cluster")))
        crds = _crds("argo-rollouts/install") + _crds("cnpg/install")
        server.apply(dump(crds), "--force-conflicts")
        server.kubectl("wait", "--for=condition=Established", *(f"crd/{c['metadata']['name']}" for c in crds),
                       "--timeout=60s")  # fmt: skip
        _wait_until_policies_enforce(server)
        yield server
    finally:
        server.stop()


@pytest.mark.parametrize("env", ENVS)
def test_environment_is_accepted_by_schemas_and_policies(api: ApiServer, env: str) -> None:
    docs = render(f"envs/{env}")
    r = api.kubectl("apply", "--server-side", "--field-manager=test", "--validate=strict",
                    "--dry-run=server", "-f", "-", stdin=dump(docs), check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert "Warning" not in r.stderr, r.stderr


@pytest.mark.parametrize("env", ENVS)
def test_database_tier_is_accepted_by_the_operator_schemas(api: ApiServer, env: str) -> None:
    docs = render(f"data/envs/{env}")
    api.apply(dump([d for d in docs if d["kind"] == "Namespace"]))
    r = api.kubectl("apply", "--server-side", "--field-manager=test", "--validate=strict",
                    "--dry-run=server", "-f", "-", stdin=dump(docs), check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr


def test_dr_drill_manifest_is_accepted(api: ApiServer) -> None:
    api.kubectl("create", "namespace", "rag-data", check=False)
    doc = _load("dr_drill").render("2026-10-13 08:59:00+00:00")
    r = api.kubectl(
        "create",
        "--validate=strict",
        "--dry-run=server",
        "-f",
        "-",
        stdin=json.dumps(doc),
        check=False,
    )
    assert r.returncode == 0, r.stderr


def test_a_typo_in_a_rollout_is_refused(api: ApiServer) -> None:
    rollout = copy.deepcopy(by(render("envs/prod"), "Rollout", "rag-api"))
    rollout["metadata"]["namespace"] = "rag"
    rollout["spec"]["strategy"]["canary"]["steps"][1] = {"pauze": {"duration": "15m"}}
    r = api.kubectl("create", "--validate=strict", "--dry-run=server", "-f", "-",
                    stdin=json.dumps(rollout), check=False)  # fmt: skip
    assert r.returncode != 0
    assert "pauze" in r.stderr


def test_an_unhardened_cronjob_is_refused(api: ApiServer) -> None:
    """Step 37 widened the workload policy to Jobs and CronJobs: a scheduled job is a pod too."""
    job = copy.deepcopy(by(render("envs/prod"), "CronJob", "rag-retention"))
    job["metadata"]["namespace"] = "rag"
    spec = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    del spec["containers"][0]["resources"]["limits"]
    r = create(api, job)
    assert r.returncode != 0
    assert "rag-workloads-hardened" in r.stderr


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


assert ZERO  # the placeholder digest used by render()
