#!/usr/bin/env python3
"""Promotion gates (Step 37): may this digest move into that environment?

    gates.py check prod sha256:… --evidence release-evidence/ [--alertmanager URL]
    gates.py record search-eval sha256:… pass --summary "recall 0.91" --out release-evidence/

The rules live in deploy/envs/promotion.yaml. Every failed rule is reported, not just the first,
so one run tells you everything that's missing. Nothing here changes any file but evidence.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENVS = ROOT / "deploy" / "envs"
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")

Now = Callable[[], dt.datetime]
Alerts = Callable[[str, dict[str, str]], list[dict[str, Any]]]


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def load_rules(envs: Path = ENVS) -> dict[str, Any]:
    return dict(yaml.safe_load((envs / "promotion.yaml").read_text()))


def current_digest(env: str, envs: Path = ENVS) -> str | None:
    doc = yaml.safe_load((envs / env / "kustomization.yaml").read_text())
    for image in doc.get("images", []):
        if image.get("name") == "rag-api":
            d = str(image.get("digest", ""))
            return d if DIGEST.match(d) else None
    return None


def running_since(env: str, digest: str, envs: Path = ENVS) -> dt.datetime | None:
    """When the digest entered the environment: the commit that added it to the overlay.
    The time of the MERGE into main is what counts (that's when Argo CD deployed it)."""
    path = envs / env / "kustomization.yaml"
    out = subprocess.run(  # noqa: S603 - fixed program, list arguments, digest validated
        ["git", "log", "--first-parent", "--format=%ct", "-S", digest, "--", str(path)],  # noqa: S607
        cwd=envs, capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    # newest first; -S lists commits that changed the number of occurrences: added AND removed.
    # The digest is there now (checked by the caller), so the newest such commit added it.
    return dt.datetime.fromtimestamp(int(out[0]), dt.UTC) if out else None


def alertmanager(url: str) -> Alerts:  # pragma: no cover - network
    import httpx

    def firing(environment: str, matchers: dict[str, str]) -> list[dict[str, Any]]:
        filters = [f'environment="{environment}"'] + [f'{k}="{v}"' for k, v in matchers.items()]
        r = httpx.get(f"{url.rstrip('/')}/api/v2/alerts",
                      params={"active": "true", "silenced": "false", "inhibited": "false", "filter": filters},
                      timeout=10)  # fmt: skip
        r.raise_for_status()
        return list(r.json())

    return firing


def check(env: str, digest: str, *, evidence: Path | None, envs: Path = ENVS,
          alerts: Alerts | None = None, now: Now = _utcnow) -> list[str]:  # fmt: skip
    """Every reason this promotion must not happen. Empty list = go."""
    if not DIGEST.match(digest):
        return [f"not an image digest: {digest!r}"]
    rules = load_rules(envs)
    if env not in rules["environments"]:
        return [f"no promotion rules for {env!r} (known: {', '.join(rules['environments'])})"]
    rule = rules["environments"][env] or {}
    problems: list[str] = []
    today = now().date()
    for w in rule.get("freeze", []):
        if dt.date.fromisoformat(w["from"]) <= today <= dt.date.fromisoformat(w["to"]):
            problems.append(f"change freeze until {w['to']}: {w['reason']}")
    source = rule.get("from")
    if source:
        running = current_digest(source, envs)
        if running != digest:
            problems.append(
                f"{source} runs {running or 'nothing'}, not this digest: promote to {source} first"
            )
        else:
            since = running_since(source, digest, envs)
            need = dt.timedelta(hours=float(rule.get("soak_hours", 0)))
            if since is None:
                problems.append(f"can't tell from git when {source} got this digest")
            elif now() - since < need:
                left = need - (now() - since)
                problems.append(
                    f"soaking in {source} for {_hours(now() - since)} of {_hours(need)}: {_hours(left)} to go"
                )
    max_age = dt.timedelta(days=float(rule.get("max_evidence_age_days", 3650)))
    for name in rule.get("evidence", []):
        problems += _evidence(evidence, name, digest, max_age, now)
    if rule.get("alerts_clear") and source:
        if alerts is None:
            problems.append("alerts can't be checked: pass --alertmanager URL")
        else:
            firing = alerts(source, dict(rule["alerts_clear"]))
            for a in firing:
                problems.append(
                    f"alert firing in {source}: {a.get('labels', {}).get('alertname', '?')}"
                )
    return problems


def _evidence(
    folder: Path | None, name: str, digest: str, max_age: dt.timedelta, now: Now
) -> list[str]:
    if folder is None:
        return [f"evidence {name}: no evidence folder given (--evidence)"]
    path = folder / f"{digest.removeprefix('sha256:')[:12]}-{name}.json"
    if not path.is_file():
        return [f"evidence {name}: missing ({path.name})"]
    try:
        e = json.loads(path.read_text())
    except json.JSONDecodeError:
        return [f"evidence {name}: not valid JSON"]
    if e.get("digest") != digest:
        return [f"evidence {name}: recorded for {e.get('digest')}, not this digest"]
    if e.get("check") != name:
        return [f"evidence {name}: the file says it is {e.get('check')!r}"]
    if e.get("status") != "pass":
        return [f"evidence {name}: status {e.get('status')!r} ({e.get('summary', '')})"]
    created = dt.datetime.fromisoformat(e["created"])
    if now() - created > max_age:
        return [
            f"evidence {name}: {(now() - created).days} days old (limit {max_age.days}): run it again"
        ]
    return []


def record(
    name: str, digest: str, status: str, summary: str, out: Path, now: Now = _utcnow
) -> Path:
    if not DIGEST.match(digest):
        raise ValueError(f"not an image digest: {digest!r}")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{digest.removeprefix('sha256:')[:12]}-{name}.json"
    path.write_text(json.dumps({"check": name, "digest": digest, "status": status, "summary": summary,
                                "created": now().isoformat(timespec="seconds")}, indent=2) + "\n")  # fmt: skip
    return path


def _hours(d: dt.timedelta) -> str:
    return f"{d.total_seconds() / 3600:.1f} h"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gates.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("env")
    c.add_argument("digest")
    c.add_argument("--evidence", type=Path)
    c.add_argument("--alertmanager", help="Alertmanager URL of the environment promoted FROM")
    r = sub.add_parser("record")
    r.add_argument("name")
    r.add_argument("digest")
    r.add_argument("status", choices=["pass", "fail"])
    r.add_argument("--summary", default="")
    r.add_argument("--out", type=Path, default=Path("release-evidence"))
    a = ap.parse_args(argv)
    if a.cmd == "record":
        print(record(a.name, a.digest, a.status, a.summary, a.out))
        return 0
    problems = check(a.env, a.digest, evidence=a.evidence,
                     alerts=alertmanager(a.alertmanager) if a.alertmanager else None)  # fmt: skip
    for p in problems:
        print(f"BLOCKED: {p}", file=sys.stderr)
    print(
        f"{a.env} <- {a.digest}: {'all gates pass' if not problems else f'{len(problems)} gate(s) failed'}"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
