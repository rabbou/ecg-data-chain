"""Check the corpora on disk against the checksums their publishers released.

This is a heavy pass -- 53 GB read, hashed once -- so it runs under a capped
scope, one at a time, per the programme's rule 7:

    systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
        uv run python scripts/verify_manifests.py

It writes results/manifest_report.json and exits non-zero if any file differs
from what its publisher declared or is missing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ecgchain.manifest import parse_manifest, verify  # noqa: E402
from ecgchain.sources import Source, sources  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"


def check(entry: Source) -> dict[str, object]:
    started = time.monotonic()
    manifest = parse_manifest(entry.manifest, entry.manifest_prefix)
    report = verify(entry.source_id, manifest, entry.directory)
    return {
        "source_id": report.source_id,
        "corpus": entry.corpus,
        "distribution": entry.distribution,
        "version": entry.version,
        "n_declared": report.n_declared,
        "n_checked": report.n_checked,
        "matched": report.matched,
        "mismatched": report.mismatched,
        "missing_on_disk": report.missing_on_disk,
        "unlisted": report.unlisted,
        "holds": report.holds,
        "seconds": round(time.monotonic() - started, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", help="a source id; repeatable")
    args = parser.parse_args()

    wanted = [e for e in sources() if not args.source or e.source_id in args.source]
    reports = []
    for entry in wanted:
        if not entry.directory.is_dir():
            print(f"{entry.source_id}: {entry.directory} is not there", file=sys.stderr)
            return 2
        report = check(entry)
        reports.append(report)
        print(
            f"{report['source_id']}: {report['matched']}/{report['n_declared']} matched"
            f" · {len(report['mismatched'])} differ"  # type: ignore[arg-type]
            f" · {len(report['missing_on_disk'])} missing"  # type: ignore[arg-type]
            f" · {report['seconds']}s"
        )

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "manifest_report.json").write_text(json.dumps(reports, indent=2) + "\n")
    return 0 if all(r["holds"] for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
