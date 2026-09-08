"""The committed quality sweep, and what it says about each distribution.

Every number on the right-hand side was produced by reading the signals once,
on 2026-09-08. They are here so that a change to the window, the quantum or a
fault rule cannot pass unnoticed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RESULTS = Path(__file__).resolve().parents[1] / "results"
SWEEP = RESULTS / "quality_scan.json"

# source id -> (records, clean records, distinct signal fingerprints)
SWEPT = {
    "challenge-2021/chapman_shaoxing": (10247, 10228, 10234),
    "challenge-2021/cpsc_2018": (6877, 6857, 6622),
    "challenge-2021/cpsc_2018_extra": (3453, 3443, 3384),
    "challenge-2021/georgia": (10344, 10311, 10250),
    "challenge-2021/ningbo": (34905, 33322, 34902),
    "challenge-2021/ptb": (516, 516, 516),
    "challenge-2021/ptb-xl": (21837, 21514, 21801),
    "challenge-2021/st_petersburg_incart": (74, 70, 74),
    "physionet/incartdb": (75, 72, 75),
    "physionet/ptb-xl": (21799, 21476, 21799),
    "physionet/ludb": (200, 198, 200),
    "physionet/ptbdb": (549, 549, 549),
}


@pytest.fixture(scope="module")
def sweep() -> dict[str, dict]:
    if not SWEEP.exists():
        pytest.skip(f"{SWEEP} has not been written; run scripts/scan_quality.py")
    return {entry["source_id"]: entry for entry in json.loads(SWEEP.read_text())}


class TestTheCommittedSweep:
    def test_every_distribution_is_there(self, sweep: dict[str, dict]) -> None:
        assert set(sweep) == set(SWEPT)

    @pytest.mark.parametrize("source_id", sorted(SWEPT))
    def test_records_clean_and_distinct(self, sweep: dict[str, dict], source_id: str) -> None:
        entry = sweep[source_id]
        records, clean, distinct = SWEPT[source_id]
        assert entry["n_records"] == records
        assert entry["n_clean"] == clean
        assert entry["n_distinct_signal_digests"] == distinct

    @pytest.mark.parametrize("source_id", sorted(SWEPT))
    def test_the_faults_account_for_what_is_not_clean(
        self, sweep: dict[str, dict], source_id: str
    ) -> None:
        """No record is unclean without a named fault."""
        entry = sweep[source_id]
        faulty = entry["n_records"] - entry["n_clean"]
        named = (
            entry["n_with_a_missing_lead"]
            + entry["n_with_a_flat_lead"]
            + entry["n_with_a_saturated_lead"]
            + entry["n_with_nonfinite_samples"]
        )
        assert faulty <= named  # one record may carry more than one fault
        assert (faulty == 0) == (named == 0)


class TestWhatTheSweepFound:
    def test_no_record_is_missing_a_standard_lead(self, sweep: dict[str, dict]) -> None:
        """All twelve leads are present everywhere; PTB's extra three are dropped."""
        assert all(entry["n_with_a_missing_lead"] == 0 for entry in sweep.values())

    def test_ningbo_carries_most_of_the_faults(self, sweep: dict[str, dict]) -> None:
        faulty = {sid: e["n_records"] - e["n_clean"] for sid, e in sweep.items()}
        assert faulty["challenge-2021/ningbo"] == 1583
        assert faulty["challenge-2021/ningbo"] > sum(
            n for sid, n in faulty.items() if sid != "challenge-2021/ningbo"
        )

    def test_a_distribution_repeats_tracings_inside_itself(self, sweep: dict[str, dict]) -> None:
        """CPSC ships 6,877 records holding 6,622 distinct tracings.

        This is not a cross-packaging finding: it is one corpus carrying the
        same recording more than once, and it is what a split has to respect.
        """
        repeats = {sid: e["n_repeats_within"] for sid, e in sweep.items()}
        assert repeats["challenge-2021/cpsc_2018"] == 255
        assert repeats["challenge-2021/georgia"] == 94
        assert repeats["challenge-2021/cpsc_2018_extra"] == 69
        assert repeats["challenge-2021/ptb-xl"] == 36

    def test_the_physionet_distributions_repeat_nothing(self, sweep: dict[str, dict]) -> None:
        """The repackaging introduced the repeats; the originals have none."""
        originals = {sid: e for sid, e in sweep.items() if sid.startswith("physionet/")}
        assert all(entry["n_repeats_within"] == 0 for entry in originals.values())

    def test_ptbxl_repeats_only_in_its_bundled_packaging(self, sweep: dict[str, dict]) -> None:
        assert sweep["challenge-2021/ptb-xl"]["n_repeats_within"] == 36
        assert sweep["physionet/ptb-xl"]["n_repeats_within"] == 0

    def test_the_window_is_ten_seconds_at_each_corpus_rate(self, sweep: dict[str, dict]) -> None:
        assert sweep["challenge-2021/ningbo"]["window_samples"] == [5000]
        assert sweep["physionet/incartdb"]["window_samples"] == [2570]
        assert sweep["physionet/ptbdb"]["window_samples"] == [10000]
