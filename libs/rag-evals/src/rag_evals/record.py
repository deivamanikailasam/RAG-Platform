"""Write evaluation results into a model card (Step 25) without destroying its comments."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


def record_results(card: Path, results: Mapping[str, float], dataset: str, date: dt.date) -> None:
    """Add or replace one entry per metric for this dataset, keeping everything else as written."""
    yaml = YAML()  # round-trip mode: comments, order and quoting survive
    yaml.preserve_quotes = True
    yaml.width = 100
    data = yaml.load(card.read_text())
    entries = data.get("evaluation")
    if entries is None:
        entries = CommentedSeq()
        data["evaluation"] = entries
    for metric, value in sorted(results.items()):
        for i in reversed(range(len(entries))):
            if (
                entries[i]["metric"] == metric
                and entries[i]["dataset"].split("@")[0] == dataset.split("@")[0]
            ):
                del entries[i]  # replaced by the newer measurement on this dataset
        # a fresh date object per row: a shared one would be written as a YAML anchor (&id001)
        day = dt.date(date.year, date.month, date.day)
        row = CommentedMap(metric=metric, value=round(float(value), 4), dataset=dataset, date=day)
        row.fa.set_flow_style()  # one line per result: easy to read in a diff
        entries.append(row)
    buf = StringIO()
    yaml.dump(data, buf)
    card.write_text(buf.getvalue())
