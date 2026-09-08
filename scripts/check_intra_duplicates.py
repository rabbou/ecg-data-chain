"""Are a distribution's internal repeats copies, or two recordings of one person?

The fingerprint says two records hold the same ten seconds to within ten
microvolts. That is consistent with a file copied under a second id, and it is
also consistent -- barely -- with a machine writing the same numbers twice. The
difference matters: a copy is a duplicate a split must not straddle, two
acquisitions are two data points.

The test that separates them is exact equality of the raw samples over the
whole record, not the ten-second window the fingerprint uses. Two acquisitions
of one patient agree on the beat and disagree on every sample; a copy agrees on
every sample of every lead for the whole recording.

    systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
        uv run python scripts/check_intra_duplicates.py --source challenge-2021/cpsc_2018
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import wfdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ecgchain.duplicates import groups  # noqa: E402
from ecgchain.heavy import holding  # noqa: E402
from ecgchain.ingest import headers  # noqa: E402
from ecgchain.sources import source  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"
CACHE = RESULTS / "cache" / "signal_digests.json"


def _read(path: Path) -> tuple[Any, np.ndarray]:
    meta = wfdb.rdrecord(str(path.with_suffix("")))
    return meta, np.asarray(meta.p_signal, dtype=np.float64)


def compare(first: Path, second: Path) -> dict[str, object]:
    """Everything that separates a copy from a second acquisition."""
    left_meta, left = _read(first)
    right_meta, right = _read(second)
    n = min(left.shape[0], right.shape[0])
    same_shape = left.shape == right.shape
    both = left[:n], right[:n]
    finite = np.isfinite(both[0]) & np.isfinite(both[1])
    identical = bool(same_shape and np.array_equal(both[0][finite], both[1][finite]))
    lead_one = np.corrcoef(both[0][finite[:, 0], 0], both[1][finite[:, 0], 0])[0, 1]
    return {
        "records": [first.stem, second.stem],
        "same_shape": same_shape,
        "shapes": [list(left.shape), list(right.shape)],
        "identical_samples": identical,
        "max_absolute_difference": float(np.nanmax(np.abs(both[0] - both[1]))),
        "lead_one_correlation": round(float(lead_one), 9),
        "comments": [list(left_meta.comments or []), list(right_meta.comments or [])],
        "same_comments": list(left_meta.comments or []) == list(right_meta.comments or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="a source id from the catalogue")
    parser.add_argument("--sample", type=int, default=20, help="how many groups to open")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    with holding("heavy", "scripts/check_intra_duplicates.py"):
        entry = source(args.source)
        digests: dict[str, dict[str, str | None]] = json.loads(CACHE.read_text())
        repeated = [
            members for members in groups(digests[entry.source_id]).values() if len(members) > 1
        ]
        if not repeated:
            print(f"{entry.source_id} repeats nothing", file=sys.stderr)
            return 1

        by_stem = {header.stem: header for header in headers(entry)}
        rng = np.random.default_rng(args.seed)
        chosen = rng.choice(len(repeated), size=min(args.sample, len(repeated)), replace=False)

        checked: list[dict[str, object]] = []
        correlations: list[float] = []
        for index in sorted(int(i) for i in chosen):
            members = repeated[index]
            first, second = (record.split(":", 1)[1] for record in members[:2])
            pair = compare(by_stem[first], by_stem[second])
            checked.append(pair)
            correlations.append(float(str(pair["lead_one_correlation"])))

        report = {
            "source_id": entry.source_id,
            "n_groups": len(repeated),
            "n_checked": len(checked),
            "seed": args.seed,
            "n_identical_samples": sum(1 for c in checked if c["identical_samples"]),
            "n_same_comments": sum(1 for c in checked if c["same_comments"]),
            "lowest_correlation": min(correlations),
            "pairs": checked,
        }
        RESULTS.mkdir(exist_ok=True)
        name = entry.source_id.replace("/", "_")
        (RESULTS / f"intra_duplicate_check_{name}.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(
            f"{entry.source_id}: {report['n_identical_samples']}/{report['n_checked']}"
            f" pairs identical sample for sample"
            f" · lowest lead-I correlation {report['lowest_correlation']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
