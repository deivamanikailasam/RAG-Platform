"""A real Kubernetes API server for tests (Step 29): etcd + kube-apiserver, no nodes.

Objects are stored, validated and admitted exactly as in a cluster (schemas, Pod Security,
ValidatingAdmissionPolicy, RBAC, service account tokens). Nothing is scheduled: Pods stay Pending.
Binaries: `just tools kube-apiserver etcd kubectl` (the "envtest" builds from kubernetes-sigs).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BINARIES = ("etcd", "kube-apiserver", "kubectl")


def available() -> bool:
    return all(shutil.which(b) for b in BINARIES) and shutil.which("openssl") is not None


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _openssl(*args: str) -> None:
    subprocess.run(["openssl", *args], check=True, capture_output=True)  # noqa: S603, S607


@dataclass
class ApiServer:
    root: Path
    url: str = ""
    kubeconfig: Path = field(init=False)
    _procs: list[subprocess.Popen[bytes]] = field(default_factory=list)

    def start(self) -> ApiServer:
        pki = self.root / "pki"
        pki.mkdir(parents=True)
        # A cluster CA, an admin client certificate (group system:masters) and the key that
        # signs service account tokens: what kubeadm or OrbStack would create for you.
        _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=test-ca",
                 "-keyout", str(pki / "ca.key"), "-out", str(pki / "ca.crt"))  # fmt: skip
        _openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", "/O=system:masters/CN=admin",
                 "-keyout", str(pki / "admin.key"), "-out", str(pki / "admin.csr"))  # fmt: skip
        _openssl("x509", "-req", "-in", str(pki / "admin.csr"), "-CA", str(pki / "ca.crt"),
                 "-CAkey", str(pki / "ca.key"), "-CAcreateserial", "-days", "1",
                 "-out", str(pki / "admin.crt"))  # fmt: skip
        _openssl("genrsa", "-out", str(pki / "sa.key"), "2048")
        _openssl("rsa", "-in", str(pki / "sa.key"), "-pubout", "-out", str(pki / "sa.pub"))
        etcd_port, peer, api = _port(), _port(), _port()
        log = (self.root / "etcd.log").open("w")
        self._procs.append(subprocess.Popen(  # noqa: S603
            ["etcd", f"--data-dir={self.root / 'etcd'}",  # noqa: S607
             f"--listen-client-urls=http://127.0.0.1:{etcd_port}",
             f"--advertise-client-urls=http://127.0.0.1:{etcd_port}",
             f"--listen-peer-urls=http://127.0.0.1:{peer}",
             f"--initial-advertise-peer-urls=http://127.0.0.1:{peer}",
             f"--initial-cluster=default=http://127.0.0.1:{peer}"],
            stdout=log, stderr=subprocess.STDOUT,
        ))  # fmt: skip
        log = (self.root / "apiserver.log").open("w")
        self._procs.append(subprocess.Popen(  # noqa: S603
            ["kube-apiserver", f"--etcd-servers=http://127.0.0.1:{etcd_port}",  # noqa: S607
             f"--cert-dir={self.root / 'serving'}", f"--secure-port={api}", "--bind-address=127.0.0.1",
             "--service-cluster-ip-range=10.96.0.0/16", f"--client-ca-file={pki / 'ca.crt'}",
             "--authorization-mode=RBAC", "--allow-privileged=true",
             "--service-account-issuer=https://kubernetes.default.svc.cluster.local",
             f"--service-account-key-file={pki / 'sa.pub'}",
             f"--service-account-signing-key-file={pki / 'sa.key'}"],
            stdout=log, stderr=subprocess.STDOUT,
        ))  # fmt: skip
        self.url = f"https://127.0.0.1:{api}"
        self.kubeconfig = self.root / "kubeconfig"
        self.kubeconfig.write_text(json.dumps({
            "apiVersion": "v1", "kind": "Config", "current-context": "test",
            "clusters": [{"name": "test", "cluster": {"server": self.url, "insecure-skip-tls-verify": True}}],
            "users": [{"name": "admin", "user": {"client-certificate": str(pki / "admin.crt"),
                                                 "client-key": str(pki / "admin.key")}}],
            "contexts": [{"name": "test", "context": {"cluster": "test", "user": "admin"}}],
        }))  # fmt: skip
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            r = self.kubectl("get", "--raw=/readyz", check=False)
            if r.returncode == 0 and r.stdout.strip() == "ok":
                return self
            time.sleep(0.5)
        self.stop()
        raise RuntimeError(
            "kube-apiserver did not become ready:\n"
            + (self.root / "apiserver.log").read_text()[-3000:]
        )

    def stop(self) -> None:
        for p in reversed(self._procs):
            p.terminate()
            p.wait(15)
        self._procs.clear()

    @property
    def serving_ca(self) -> str:
        """The API server's own (self-signed) serving certificate, for clients that verify TLS."""
        return (self.root / "serving" / "apiserver.crt").read_text()

    def kubectl(
        self, *args: str, stdin: str | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
        return subprocess.run(  # noqa: S603
            ["kubectl", f"--kubeconfig={self.kubeconfig}", *args], input=stdin,  # noqa: S607
            capture_output=True, text=True, check=check, env=env,
        )  # fmt: skip

    def apply(
        self, manifests: str, *extra: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return self.kubectl("apply", "--server-side", "--field-manager=test", "-f", "-", *extra,
                            stdin=manifests, check=check)  # fmt: skip

    def get(self, *args: str) -> Any:
        return json.loads(self.kubectl("get", *args, "-o", "json").stdout)
