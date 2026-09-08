"""Where the screen's memory goes, phase by phase, on one pair of packagings.

A full screen peaked at 2.44 GB on the cgroup counter and 1.6 GB in the journal
at teardown. The three obvious candidates account for 46 MB of that: the
interpreter and its imports at 36.6 MB, the fingerprint cache at 22.0 MB, the
Challenge manifest filtered to one corpus at 8.9 MB. Guessing at the rest has
been wrong three times, so this measures it instead.

It runs the phases of ``scan_quality.screen`` in order on one corpus, reporting
what ``tracemalloc`` attributes to each and the resident size after it. INCART
is the pair to use: 149 records between the two packagings, and its holters are
the largest single arrays in the delivery, so whichever of the two dominates
shows up on a corpus small enough to profile under a 1 GB cap.

    systemd-run --user --scope --unit=lab-heavy-tracemalloc-incart \
        -p MemoryMax=1G uv run python scripts/profile_screen.py

It writes results/screen_profile.json and no delivery table.
"""

from __future__ import annotations

import argparse
import json
import linecache
import resource
import sys
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scan_quality import file_digests, lead_one, stream_lead_one  # noqa: E402

from ecgchain.duplicates import by_digest, correlate, unmatched  # noqa: E402
from ecgchain.sources import source  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"
CACHE = RESULTS / "cache" / "signal_digests.json"


def rss_mb() -> float:
    """Resident size of this process, the number a memory cap acts on."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


class Phase:
    """One step of the screen, with what it allocated and what it left behind."""

    def __init__(self, name: str, log: list[dict[str, object]]) -> None:
        self.name, self.log = name, log

    def __enter__(self) -> Phase:
        tracemalloc.reset_peak()
        self.before = tracemalloc.get_traced_memory()[0]
        self.rss_before = rss_mb()
        return self

    def __exit__(self, *_: object) -> None:
        current, peak = tracemalloc.get_traced_memory()
        self.log.append(
            {
                "phase": self.name,
                "kept_MB": round((current - self.before) / 1e6, 1),
                "peak_MB": round(peak / 1e6, 1),
                "rss_before_MB": round(self.rss_before, 1),
                "rss_after_MB": round(rss_mb(), 1),
            }
        )
        print(f"  {self.log[-1]}", flush=True)


def top_allocations(limit: int = 8) -> list[dict[str, object]]:
    """The lines holding the most memory when the screen is at its widest."""
    snapshot = tracemalloc.take_snapshot().filter_traces(
        (tracemalloc.Filter(False, tracemalloc.__file__), tracemalloc.Filter(False, "<unknown>"))
    )
    top = []
    for stat in snapshot.statistics("lineno")[:limit]:
        frame = stat.traceback[0]
        top.append(
            {
                "where": f"{Path(frame.filename).name}:{frame.lineno}",
                "MB": round(stat.size / 1e6, 2),
                "line": linecache.getline(frame.filename, frame.lineno).strip()[:90],
            }
        )
    return top


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", default="challenge-2021/st_petersburg_incart")
    parser.add_argument("--right", default="physionet/incartdb")
    args = parser.parse_args()

    left, right = source(args.left), source(args.right)
    log: list[dict[str, object]] = []
    tracemalloc.start(4)
    print(f"imports done · RSS {rss_mb():.1f} MB", flush=True)

    with Phase("load fingerprint cache", log):
        cache = json.loads(CACHE.read_text())
        digests = {left.source_id: cache[left.source_id], right.source_id: cache[right.source_id]}

    with Phase("file_digests both sides", log):
        files = {**file_digests(left), **file_digests(right)}

    with Phase("by_digest on files and signals", log):
        source_of = {r: s for s, d in digests.items() for r in d}
        by_file = by_digest(files, "source-file", source_of)
        signals = {**digests[left.source_id], **digests[right.source_id]}
        by_signal = by_digest(signals, "signal", source_of)
        links = by_file + by_signal

    with Phase("lead_one on the leftovers", log):
        left_over = set(unmatched(digests[left.source_id], links))
        targets = lead_one(left, left_over)

    with Phase("correlate against the streamed side", log):
        found = correlate(targets, stream_lead_one(right))

    top = top_allocations()
    report: dict[str, object] = {
        "left": left.source_id,
        "right": right.source_id,
        "n_links_by_digest": len(links),
        "n_links_by_correlation": len(found),
        "n_targets": len(targets),
        "phases": log,
        "rss_peak_MB": round(rss_mb(), 1),
        "top_allocations_at_the_end": top,
    }
    tracemalloc.stop()
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "screen_profile.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"RSS peak {report['rss_peak_MB']} MB")
    for row in top:
        print(f"  {row['MB']:8.2f} MB  {row['where']}  {row['line']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
