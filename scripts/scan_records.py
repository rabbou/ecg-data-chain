"""Read every header of every source and write what they declare.

A heavy pass -- 88,253 headers across 53 GB of corpora -- so it runs under a
capped scope, one at a time, per the programme's rule 7:

    systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
        uv run python scripts/scan_records.py

It writes results/record_scan.json, which the tests pin.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ecgchain.ingest import scan  # noqa: E402
from ecgchain.sources import Source, sources  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"


def summarise(entry: Source) -> dict[str, object]:
    started = time.monotonic()
    records, leads = scan(entry)
    units = Counter(unit for row in records for unit in row.units_declared)
    return {
        "source_id": entry.source_id,
        "corpus": entry.corpus,
        "distribution": entry.distribution,
        "version": entry.version,
        "n_records": len(records),
        "n_leads_rows": len(leads),
        "leads_per_record": sorted({row.n_leads for row in records}),
        "sampling_rates_hz": sorted({row.sampling_rate_hz for row in records}),
        "sample_lengths": sorted({row.n_samples for row in records})[:8],
        "units_declared": dict(sorted(units.items())),
        "n_units_declared": sum(1 for row in records if row.units_are_declared),
        "n_all_millivolts": sum(1 for row in records if row.all_millivolts),
        "n_with_dx": sum(1 for row in records if row.dx),
        "n_non_canonical_leads": sum(1 for lead in leads if lead.name_canonical is None),
        "seconds": round(time.monotonic() - started, 1),
    }


def units_of(summary: dict[str, object]) -> list[str]:
    declared = summary["units_declared"]
    assert isinstance(declared, dict)
    return list(declared)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", help="a source id; repeatable")
    args = parser.parse_args()

    wanted = [e for e in sources() if not args.source or e.source_id in args.source]
    summaries = []
    for entry in wanted:
        if not entry.directory.is_dir():
            print(f"{entry.source_id}: {entry.directory} is not there", file=sys.stderr)
            return 2
        summary = summarise(entry)
        summaries.append(summary)
        print(
            f"{summary['source_id']}: {summary['n_records']} records"
            f" · leads {summary['leads_per_record']}"
            f" · units {sorted(units_of(summary))}"
            f" · {summary['seconds']}s"
        )

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "record_scan.json").write_text(json.dumps(summaries, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
