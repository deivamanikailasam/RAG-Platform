#!/usr/bin/env python3
"""Check the licence of every installed Python dependency against ci/licence-policy.yaml (Step 27).

Reads each package's own metadata, in order of reliability: the SPDX `License-Expression`
(PEP 639), then a short `License` field, then trove classifiers. Anything unclear must be
resolved by a person in `exceptions`, never guessed.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.metadata import Distribution, distributions
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]

# Old-style names and classifiers -> SPDX ids. Ambiguous ones ("BSD License") are left out on purpose.
ALIASES = {
    "mit license": "MIT", "apache license 2.0": "Apache-2.0", "apache 2.0": "Apache-2.0",
    "apache software license": "Apache-2.0", "3-clause bsd license": "BSD-3-Clause",
    "bsd-3-clause license": "BSD-3-Clause", "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "python software foundation license": "PSF-2.0", "isc license (iscl)": "ISC",
}  # fmt: skip


@dataclass(frozen=True)
class Verdict:
    package: str
    version: str
    licence: str | None
    status: str  # ok | review | denied | unknown
    note: str = ""


def declared_licence(d: Distribution) -> str | None:
    m = d.metadata
    if expr := m.get("License-Expression"):
        return str(expr).strip()
    field = (m.get("License") or "").strip()
    if field and "\n" not in field and len(field) <= 40:
        return ALIASES.get(field.lower(), field)
    found = sorted({ALIASES[c.split("::")[-1].strip().lower()] for c in m.get_all("Classifier") or []
                    if c.startswith("License ::") and c.split("::")[-1].strip().lower() in ALIASES})  # fmt: skip
    return " OR ".join(found) if found else None


def judge(expr: str, policy: Mapping[str, Any]) -> tuple[str, str]:
    """OR: the best alternative counts (we may choose). AND: the worst part counts (we must comply with all)."""
    rank = {"ok": 0, "review": 1, "unknown": 2, "denied": 3}

    def one(spdx: str) -> tuple[str, str]:
        spdx = spdx.strip("() ")
        if spdx in policy["allowed"]:
            return "ok", ""
        if spdx in policy.get("review_required", {}):
            return "review", policy["review_required"][spdx]
        if spdx in policy["denied"]:
            return "denied", f"{spdx} is not allowed"
        return "unknown", f"'{spdx}' is not in the policy"

    results = []
    for alternative in re.split(r"\s+OR\s+", expr):
        parts = [one(p) for p in re.split(r"\s+AND\s+", alternative)]
        results.append(max(parts, key=lambda r: rank[r[0]]))
    return min(results, key=lambda r: rank[r[0]])


def check(dists: Iterable[Distribution], policy: Mapping[str, Any]) -> list[Verdict]:
    out = []
    for d in dists:
        name, version = d.metadata["Name"], d.version
        if name in policy.get("ignore", []):
            continue
        exception = (policy.get("exceptions") or {}).get(name)
        expr = exception["licence"] if exception else declared_licence(d)
        if expr is None:
            out.append(
                Verdict(
                    name,
                    version,
                    None,
                    "unknown",
                    "no licence metadata: verify and add an exception",
                )
            )
            continue
        status, note = judge(expr, policy)
        out.append(
            Verdict(
                name, version, expr, status, note + (" (verified exception)" if exception else "")
            )
        )
    return sorted(out, key=lambda v: v.package.lower())


def main(argv: list[str]) -> int:
    policy = yaml.safe_load((ROOT / "ci/licence-policy.yaml").read_text())
    verdicts = check(distributions(), policy)
    for v in verdicts:
        if v.status != "ok" or "-v" in argv:
            print(f"{v.status.upper():8} {v.package} {v.version}: {v.licence} {v.note}".rstrip())
    counts = {
        s: sum(v.status == s for v in verdicts) for s in ("ok", "review", "unknown", "denied")
    }
    print(f"{len(verdicts)} packages: " + ", ".join(f"{n} {s}" for s, n in counts.items()))
    return 1 if counts["unknown"] or counts["denied"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
