"""Build the delivery: one Parquet file per grain, queryable with DuckDB.

One pass over every record, because the signals are the expensive part and
reading them twice to fill two tables would double the only pass that costs
anything.  Heavy, so it runs under a capped scope and holds the heavy lock:

    systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
        uv run python scripts/build_database.py

It writes results/delivery/*.parquet -- not committed, they are rebuilt from
the corpora -- and results/database_report.json, which the tests pin.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ecgchain.database import (  # noqa: E402
    TABLES,
    connect,
    duplicate_link_table,
    label_table,
    lead_table,
    quality_table,
    record_table,
    signal_group_table,
    source_file_table,
    source_table,
    trace,
    write,
)
from ecgchain.duplicates import ACROSS, WITHIN, DuplicateLink  # noqa: E402
from ecgchain.heavy import holding  # noqa: E402
from ecgchain.ingest import LeadRow, RecordRow, headers, read_header  # noqa: E402
from ecgchain.manifest import parse_manifest  # noqa: E402
from ecgchain.quality import QualityRow, quality_row  # noqa: E402
from ecgchain.sources import Source, sources  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"
DELIVERY = RESULTS / "delivery"
LINKS = RESULTS / "cache" / "duplicate_links.json"


def sweep(entry: Source) -> dict[str, pd.DataFrame]:
    """Every table this distribution contributes, from one pass over its records."""
    declared = (
        parse_manifest(entry.manifest, entry.manifest_prefix) if entry.manifest.exists() else {}
    )
    records: list[RecordRow] = []
    leads: list[LeadRow] = []
    judged: list[QualityRow] = []
    for header in headers(entry):
        row, lead_rows = read_header(entry, header)
        records.append(row)
        leads.extend(lead_rows)
        judged.append(quality_row(entry, header))
    return {
        "source_file": source_file_table(entry.source_id, records, declared),
        "record": record_table(records),
        "lead": lead_table(leads),
        "label": label_table(records),
        "quality": quality_table(judged),
    }


def read_links() -> list[DuplicateLink]:
    """The pairs the screen found, cached rather than recomputed here."""
    if not LINKS.exists():
        return []
    payload = json.loads(LINKS.read_text())
    return [
        DuplicateLink(
            str(link["record_a"]),
            str(link["record_b"]),
            str(link["sieve"]),
            float(link["score"]),
            str(link["scope"]),
        )
        for scope in ("within", "across")
        for link in payload.get(scope, [])
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", help="a source id; repeatable")
    args = parser.parse_args()

    with holding("heavy", "scripts/build_database.py"):
        wanted = [e for e in sources() if not args.source or e.source_id in args.source]
        started = time.monotonic()
        parts: dict[str, list[pd.DataFrame]] = {}
        for entry in wanted:
            if not entry.directory.is_dir():
                print(f"{entry.source_id}: {entry.directory} is not there", file=sys.stderr)
                return 2
            each = time.monotonic()
            for name, frame in sweep(entry).items():
                parts.setdefault(name, []).append(frame)
            print(
                f"{entry.source_id}: swept in {round(time.monotonic() - each, 1)}s",
                flush=True,
            )

        tables = {name: pd.concat(frames, ignore_index=True) for name, frames in parts.items()}
        tables["source"] = source_table(wanted)
        digests = dict(
            zip(tables["quality"]["record_id"], tables["quality"]["signal_digest"], strict=True)
        )
        tables["signal_group"] = signal_group_table(digests)
        tables["duplicate_link"] = duplicate_link_table(read_links())

        delivery = write({name: tables[name] for name in TABLES if name in tables}, DELIVERY)
        connection = connect(delivery)

        sample = connection.execute(
            "SELECT record_id FROM record USING SAMPLE 1 ROWS (reservoir, 20260908)"
        ).fetchone()
        traced = trace(connection, str(sample[0])) if sample else None

        report = {
            "tables": {name: int(len(tables[name])) for name in TABLES if name in tables},
            "n_records": int(len(tables["record"])),
            "n_distinct_signal_groups": int(tables["signal_group"]["signal_group_id"].nunique()),
            "n_records_in_a_repeated_group": int((tables["signal_group"]["group_size"] > 1).sum()),
            "duplicate_links_by_scope": {
                WITHIN: int((tables["duplicate_link"]["scope"] == WITHIN).sum()),
                ACROSS: int((tables["duplicate_link"]["scope"] == ACROSS).sum()),
            },
            "n_files_without_a_declared_digest": int(
                tables["source_file"]["sha256_declared"].isna().sum()
            ),
            "traced_example": traced,
            "seconds": round(time.monotonic() - started, 1),
        }
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / "database_report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report["tables"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
