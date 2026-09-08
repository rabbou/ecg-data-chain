"""Fill the label side of the delivery: the code tables, the patients, the counts.

Light: it reads the Parquet the database build wrote, plus three published code
tables and two corpus metadata files.  No signal is opened, so it holds no lock.

    uv run python scripts/build_labels.py

It writes label_map.parquet and patient.parquet beside the other tables, and
results/label_report.json, which the tests pin against the counts the Challenge
organisers published.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ecgchain.database import DEFERRED, Delivery, connect, propagate_labels  # noqa: E402
from ecgchain.labels import (  # noqa: E402
    PARTITION_TO_SOURCE,
    bundle_record_id,
    label_map_table,
    patient_table,
    published_counts,
    scored_table,
)
from ecgchain.sources import sources  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"
DELIVERY = RESULTS / "delivery"


def counts_per_source(label: pd.DataFrame, record: pd.DataFrame) -> dict[tuple[str, str], int]:
    """(distribution, code) -> how many of its records carry that code."""
    joined = label.merge(record[["record_id", "source_id"]], on="record_id", how="left")
    pairs = Counter(zip(joined["source_id"], joined["code"].astype(str), strict=True))
    return dict(pairs)


def compare_to_published(counted: dict[tuple[str, str], int]) -> dict[str, object]:
    """Every scored class, in every partition, against the organisers' own table."""
    published = published_counts()
    disagreements = [
        {
            "source_id": source_id,
            "code": code,
            "published": expected,
            "counted": counted.get((source_id, code), 0),
        }
        for (source_id, code), expected in published.items()
        if counted.get((source_id, code), 0) != expected
    ]
    return {
        "n_cells": len(published),
        "n_agreeing": len(published) - len(disagreements),
        "disagreements": disagreements[:20],
        "n_disagreements": len(disagreements),
    }


def ptbxl_join(record: pd.DataFrame) -> dict[str, object]:
    """The published naming convention against the fingerprint the screen used.

    The bundle names PTB-XL record HR<ecg_id padded to five>.  That is an
    independent answer to the question the signal screen answered, so the two
    are compared rather than either being taken on trust.
    """
    original = record[record["source_id"] == "physionet/ptb-xl"]["native_record_id"]
    bundled = set(record[record["source_id"] == "challenge-2021/ptb-xl"]["native_record_id"])
    by_name = {
        native: bundle_record_id(int(native.split("_", 1)[0]))
        for native in original
        if native.endswith("_hr")
    }
    matched = {a: b for a, b in by_name.items() if b in bundled}
    return {
        "n_original": int(len(original)),
        "n_bundled": len(bundled),
        "n_matched_by_name": len(matched),
        "n_original_without_a_named_twin": int(len(original)) - len(matched),
        "n_bundled_not_named_by_any_original": len(bundled - set(matched.values())),
    }


def main() -> int:
    delivery = Delivery(DELIVERY)
    if "record" not in delivery.present:
        print(f"{DELIVERY} has no record table; run scripts/build_database.py", file=sys.stderr)
        return 2
    connection = connect(delivery)
    record = connection.execute("SELECT * FROM record").fetch_df()
    label = connection.execute("SELECT * FROM label").fetch_df()

    links = connection.execute("SELECT * FROM duplicate_link").fetch_df()
    propagated = propagate_labels(label, links, record)
    propagated.to_parquet(delivery.path("label_propagated"), index=False)

    mapping = label_map_table()
    patients = pd.concat(
        [patient_table(entry.source_id, entry.directory) for entry in sources()],
        ignore_index=True,
    )
    mapping.to_parquet(delivery.path("label_map"), index=False)
    patients.to_parquet(delivery.path("patient"), index=False)

    counted = counts_per_source(label, record)
    carrying = set(patients["source_id"].dropna().unique())
    report = {
        "n_label_rows": int(len(label)),
        "n_propagated_label_rows": int(len(propagated)),
        "propagated_by_source": {
            str(name): int(count) for name, count in propagated["source_id"].value_counts().items()
        },
        "n_records_given_a_propagated_label": int(propagated["record_id"].nunique()),
        "deferred_tables": list(DEFERRED),
        "n_label_map_rows": int(len(mapping)),
        "label_map_by_source": {
            str(name): int(count) for name, count in mapping["map_source"].value_counts().items()
        },
        "n_patients": int(patients["patient_id"].nunique()),
        "patients_by_source": {
            str(name): int(count)
            for name, count in patients.groupby("source_id")["patient_id"].nunique().items()
        },
        "distributions_publishing_no_patient_key": sorted(
            entry.source_id for entry in sources() if entry.source_id not in carrying
        ),
        "n_scored_classes": int(len(scored_table())),
        "partitions_checked": sorted(PARTITION_TO_SOURCE.values()),
        "published_comparison": compare_to_published(counted),
        "ptbxl_named_join": ptbxl_join(record),
    }
    (RESULTS / "label_report.json").write_text(json.dumps(report, indent=2) + "\n")
    comparison = report["published_comparison"]
    assert isinstance(comparison, dict)
    print(
        f"{comparison['n_agreeing']}/{comparison['n_cells']} published cells agree"
        f" · {report['n_patients']} patients"
        f" · {report['n_label_map_rows']} mapping rows"
        f" · {report['n_propagated_label_rows']} propagated labels"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
