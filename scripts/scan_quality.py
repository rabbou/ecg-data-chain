"""Read every signal once: judge it, fingerprint it, then screen for duplicates.

The heaviest pass in the chain -- 110,876 records, every sample of the first
ten seconds -- so it runs under a capped scope, one at a time, per the
programme's rule 7:

    systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
        uv run python scripts/scan_quality.py

It writes results/quality_scan.json (a report per distribution) and
results/duplicate_scan.json (the links, by corpus that arrives twice).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import wfdb
from numpy.typing import NDArray

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ecgchain.duplicates import (  # noqa: E402
    ACROSS,
    WITHIN,
    DuplicateLink,
    by_digest,
    correlate,
    groups,
    merge,
    unmatched,
)
from ecgchain.heavy import holding  # noqa: E402
from ecgchain.ingest import headers, read_header  # noqa: E402
from ecgchain.manifest import parse_manifest  # noqa: E402
from ecgchain.quality import canonical_window, quality_row  # noqa: E402
from ecgchain.sources import Source, sources  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"
CACHE = RESULTS / "cache" / "signal_digests.json"  # not committed: 110,876 entries
LINKS = RESULTS / "cache" / "duplicate_links.json"  # not committed: the pairs themselves


def file_digests(entry: Source) -> dict[str, str]:
    """Record id -> the publisher's digest of its signal file."""
    if not entry.manifest.exists():
        return {}
    manifest = parse_manifest(entry.manifest, entry.manifest_prefix)
    digests: dict[str, str] = {}
    for header in headers(entry):
        row, _ = read_header(entry, header)
        folder = Path(row.header_path).parent
        for name in row.signal_paths:
            declared = manifest.get((folder / name).as_posix())
            if declared is not None:
                digests[row.record_id] = declared
                break
    return digests


def sweep(entry: Source) -> tuple[dict[str, object], dict[str, str | None]]:
    started = time.monotonic()
    rows = [quality_row(entry, header) for header in headers(entry)]
    missing = Counter(lead for row in rows for lead in row.missing_leads)
    flat = Counter(lead for row in rows for lead in row.flat_leads)
    saturated = Counter(lead for row in rows for lead in row.saturated_leads)
    report = {
        "source_id": entry.source_id,
        "corpus": entry.corpus,
        "distribution": entry.distribution,
        "n_records": len(rows),
        "n_clean": sum(1 for row in rows if row.holds),
        "n_with_a_missing_lead": sum(1 for row in rows if row.missing_leads),
        "n_with_a_flat_lead": sum(1 for row in rows if row.flat_leads),
        "n_with_a_saturated_lead": sum(1 for row in rows if row.saturated_leads),
        "n_with_nonfinite_samples": sum(1 for row in rows if row.n_nonfinite),
        "missing_by_lead": dict(sorted(missing.items())),
        "flat_by_lead": dict(sorted(flat.items())),
        "saturated_by_lead": dict(sorted(saturated.items())),
        "window_samples": sorted({row.n_samples_read for row in rows}),
        "n_distinct_signal_digests": len({row.signal_digest for row in rows} - {None}),
        "n_repeats_within": len(rows) - len({row.signal_digest for row in rows} - {None}),
        "seconds": round(time.monotonic() - started, 1),
    }
    return report, {row.record_id: row.signal_digest for row in rows}


def lead_one(entry: Source, record_ids: set[str]) -> dict[str, NDArray[np.float32]]:
    """Lead I of the named records, for the correlation sieve."""
    windows: dict[str, NDArray[np.float32]] = {}
    for header in headers(entry):
        record_id = f"{entry.source_id}:{header.stem}"
        if record_id not in record_ids:
            continue
        meta = wfdb.rdrecord(str(header.with_suffix("")))
        window, _ = canonical_window(
            np.asarray(meta.p_signal, dtype=np.float64), list(meta.sig_name), float(meta.fs)
        )
        if window is not None:
            windows[record_id] = window[0]
    return windows


def within_distribution(entry: Source, digests: dict[str, str | None]) -> dict[str, object]:
    """What one distribution repeats inside itself.

    Only the fingerprint sieve runs here: correlating 34,905 records against
    each other is 609 million pairs, and the question a split needs answered --
    which records are the same tracing under two ids -- is one the fingerprint
    already answers.
    """
    source_of = dict.fromkeys(digests, entry.source_id)
    links = [link for link in by_digest(digests, "signal", source_of) if link.scope == WITHIN]
    repeated = {digest: members for digest, members in groups(digests).items() if len(members) > 1}
    in_a_group = sum(len(members) for members in repeated.values())
    return {
        "source_id": entry.source_id,
        "corpus": entry.corpus,
        "distribution": entry.distribution,
        "n_records": len(digests),
        "n_pairs": len(links),
        "n_groups": len(repeated),
        "n_records_in_a_group": in_a_group,
        "largest_group": max((len(m) for m in repeated.values()), default=0),
        "n_distinct_tracings": len(digests) - (in_a_group - len(repeated)),
        "examples": [members for members in list(repeated.values())[:3]],
    }


def screen(
    pair: list[Source], digests: dict[str, dict[str, str | None]]
) -> tuple[dict[str, object], list[DuplicateLink]]:
    """The three sieves over two packagings of one corpus."""
    left, right = pair
    started = time.monotonic()

    source_of = {
        record_id: entry.source_id for entry in pair for record_id in digests[entry.source_id]
    }
    files: dict[str, str | None] = {**file_digests(left), **file_digests(right)}
    by_file = [link for link in by_digest(files, "source-file", source_of) if link.scope == ACROSS]

    signals: dict[str, str | None] = {**digests[left.source_id], **digests[right.source_id]}
    by_signal = [link for link in by_digest(signals, "signal", source_of) if link.scope == ACROSS]

    links = merge(by_file, by_signal)
    left_over = set(unmatched(digests[left.source_id], links))
    right_over = set(unmatched(digests[right.source_id], links))

    # Each side's leftovers go against the whole of the other side, not against
    # the other side's leftovers.  A record can be a near-duplicate of one that
    # is already linked to somebody else -- two of PTB-XL's are exactly that --
    # and gating on both sides having leftovers hides them.
    correlation: list[DuplicateLink] = []
    note = ""
    try:
        if left_over:
            correlation += correlate(
                lead_one(left, left_over), lead_one(right, set(digests[right.source_id]))
            )
        if right_over:
            correlation += correlate(
                lead_one(right, right_over), lead_one(left, set(digests[left.source_id]))
            )
    except ValueError as error:
        note = str(error)
    links = merge(by_file, by_signal, correlation)

    report: dict[str, object] = {
        "corpus": left.corpus,
        "sources": [left.source_id, right.source_id],
        "n_records": {e.source_id: len(digests[e.source_id]) for e in pair},
        "linked_by_source_file": sum(1 for link in links if link.sieve == "source-file"),
        "linked_by_signal": sum(1 for link in links if link.sieve == "signal"),
        "linked_by_correlation": sum(1 for link in links if link.sieve == "correlation"),
        "n_linked_pairs": len(links),
        "unmatched": {
            left.source_id: sorted(set(unmatched(digests[left.source_id], links))),
            right.source_id: sorted(set(unmatched(digests[right.source_id], links))),
        },
        "shared_native_ids": sorted(
            {r.split(":", 1)[1] for r in digests[left.source_id]}
            & {r.split(":", 1)[1] for r in digests[right.source_id]}
        ),
        "note": note,
        "seconds": round(time.monotonic() - started, 1),
    }
    return report, links


def main() -> int:
    with holding("heavy", "scripts/scan_quality.py"):
        return _run()


def _run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", help="a source id; repeatable")
    parser.add_argument(
        "--reuse-digests",
        action="store_true",
        help="screen again from the cached fingerprints, without re-reading the signals",
    )
    args = parser.parse_args()

    wanted = [e for e in sources() if not args.source or e.source_id in args.source]
    reports: list[dict[str, object]] = []
    digests: dict[str, dict[str, str | None]] = {}

    if args.reuse_digests:
        if not CACHE.exists():
            print(f"{CACHE} is not there; run without --reuse-digests once", file=sys.stderr)
            return 2
        digests = json.loads(CACHE.read_text())
        reports = json.loads((RESULTS / "quality_scan.json").read_text())
        wanted = [e for e in wanted if e.source_id in digests]

    for entry in [] if args.reuse_digests else wanted:
        if not entry.directory.is_dir():
            print(f"{entry.source_id}: {entry.directory} is not there", file=sys.stderr)
            return 2
        report, signal_digests = sweep(entry)
        digests[entry.source_id] = signal_digests
        reports.append(report)
        print(
            f"{report['source_id']}: {report['n_records']} records"
            f" · {report['n_clean']} clean"
            f" · {report['n_distinct_signal_digests']} distinct signals"
            f" · {report['seconds']}s",
            flush=True,
        )

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "quality_scan.json").write_text(json.dumps(reports, indent=2) + "\n")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(digests))

    inside = []
    for entry in wanted:
        result = within_distribution(entry, digests[entry.source_id])
        inside.append(result)
        if result["n_pairs"]:
            print(
                f"{result['source_id']}: {result['n_pairs']} pairs inside itself"
                f" · {result['n_groups']} groups"
                f" · {result['n_distinct_tracings']} distinct tracings",
                flush=True,
            )

    by_corpus: dict[str, list[Source]] = defaultdict(list)
    for entry in wanted:
        by_corpus[entry.corpus].append(entry)
    screens: list[dict[str, object]] = []
    across_links: list[DuplicateLink] = []
    for corpus, entries in sorted(by_corpus.items()):
        if len(entries) != 2:
            continue
        result, links = screen(entries, digests)
        screens.append(result)
        across_links.extend(links)
        print(
            f"{corpus}: {result['n_linked_pairs']} linked across"
            f" (file {result['linked_by_source_file']},"
            f" signal {result['linked_by_signal']},"
            f" correlation {result['linked_by_correlation']})"
            f" · {result['seconds']}s",
            flush=True,
        )
    # The pairs themselves are cached rather than committed: the database build
    # reads them, and 21,837 of them do not belong in a summary a reader opens.
    LINKS.parent.mkdir(parents=True, exist_ok=True)
    LINKS.write_text(
        json.dumps(
            {
                "within": [
                    {
                        "record_a": a,
                        "record_b": b,
                        "sieve": "signal",
                        "score": 1.0,
                        "scope": WITHIN,
                    }
                    for report in inside
                    for members in _repeated_members(digests[str(report["source_id"])])
                    for a, b in zip(members, members[1:], strict=False)
                ],
                "across": [
                    {
                        "record_a": link.record_a,
                        "record_b": link.record_b,
                        "sieve": link.sieve,
                        "score": link.score,
                        "scope": link.scope,
                    }
                    for link in across_links
                ],
            }
        )
    )
    (RESULTS / "duplicate_scan.json").write_text(
        json.dumps({"within": inside, "across": screens}, indent=2) + "\n"
    )
    return 0


def _repeated_members(digests: dict[str, str | None]) -> list[list[str]]:
    return [members for members in groups(digests).values() if len(members) > 1]


if __name__ == "__main__":
    raise SystemExit(main())
