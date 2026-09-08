"""The delivery as it was built on 2026-09-08, and the copy check behind it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RESULTS = Path(__file__).resolve().parents[1] / "results"
REPORT = RESULTS / "database_report.json"

ROWS = {
    "source": 12,
    "source_file": 222_301,
    "record": 110_876,
    "lead": 1_332_159,
    "label": 181_817,
    "quality": 110_876,
    "signal_group": 110_876,
    "duplicate_link": 22_908,
}


@pytest.fixture(scope="module")
def report() -> dict:
    if not REPORT.exists():
        pytest.skip(f"{REPORT} has not been written; run scripts/build_database.py")
    return json.loads(REPORT.read_text())


class TestTheTables:
    @pytest.mark.parametrize("table", sorted(ROWS))
    def test_row_count(self, report: dict, table: str) -> None:
        assert report["tables"][table] == ROWS[table]

    def test_one_row_per_record_in_the_per_record_tables(self, report: dict) -> None:
        for table in ("record", "quality", "signal_group"):
            assert report["tables"][table] == report["n_records"]

    def test_a_lead_row_for_every_channel(self, report: dict) -> None:
        """110,876 records of twelve channels, plus PTB's 549 of fifteen."""
        assert ROWS["lead"] == 110_876 * 12 + 549 * 3


class TestProvenance:
    def test_every_file_carries_the_digest_its_publisher_released(self, report: dict) -> None:
        """222,301 files, none of them relying on a digest of ours."""
        assert report["n_files_without_a_declared_digest"] == 0

    def test_a_tracing_taken_at_random_reached_its_file(self, report: dict) -> None:
        traced = report["traced_example"]
        assert traced["relative_path"]
        assert len(traced["sha256_declared"]) == 64
        assert traced["record_id"].startswith(traced["source_id"] + ":")


class TestWhatTheDeliveryHolds:
    def test_the_tracings_are_fewer_than_the_records(self, report: dict) -> None:
        """110,876 records hold 87,609 distinct tracings."""
        assert report["n_distinct_signal_groups"] == 87_609
        assert report["n_distinct_signal_groups"] < report["n_records"]

    def test_both_scopes_are_carried_and_kept_apart(self, report: dict) -> None:
        scopes = report["duplicate_links_by_scope"]
        assert scopes["within-distribution"] == 481
        assert scopes["across-distributions"] == 22_427
        assert sum(scopes.values()) == ROWS["duplicate_link"]


class TestTheCopiesAreCopies:
    """The question a fingerprint cannot answer: copy, or second acquisition?"""

    @pytest.mark.parametrize(
        ("source_id", "checked"),
        [("challenge-2021_cpsc_2018", 20), ("challenge-2021_georgia", 10)],
    )
    def test_every_pair_opened_was_identical_sample_for_sample(
        self, source_id: str, checked: int
    ) -> None:
        path = RESULTS / f"intra_duplicate_check_{source_id}.json"
        if not path.exists():
            pytest.skip(f"{path} has not been written")
        check = json.loads(path.read_text())
        assert check["n_checked"] == checked
        assert check["n_identical_samples"] == checked
        assert check["lowest_correlation"] == 1.0

    @pytest.mark.parametrize("source_id", ["challenge-2021_cpsc_2018", "challenge-2021_georgia"])
    def test_the_pairs_agree_on_age_and_sex_too(self, source_id: str) -> None:
        path = RESULTS / f"intra_duplicate_check_{source_id}.json"
        if not path.exists():
            pytest.skip(f"{path} has not been written")
        check = json.loads(path.read_text())
        assert check["n_same_comments"] == check["n_checked"]

    def test_not_one_sample_differed(self) -> None:
        path = RESULTS / "intra_duplicate_check_challenge-2021_cpsc_2018.json"
        if not path.exists():
            pytest.skip(f"{path} has not been written")
        check = json.loads(path.read_text())
        assert max(pair["max_absolute_difference"] for pair in check["pairs"]) == 0.0


@pytest.mark.data
class TestTheSplitKeyIsSafe:
    """The invariant that makes `signal_group` usable for drawing a fold.

    Every link the screen found, whichever sieve found it, has to land inside
    one group. A group built from fingerprints alone failed this on all 587
    correlation links, which included every one of PTB's 516 cross-packaging
    pairs.
    """

    @staticmethod
    def _delivery() -> tuple:
        import pandas as pd

        delivery = RESULTS / "delivery"
        links = delivery / "duplicate_link.parquet"
        groups = delivery / "signal_group.parquet"
        if not links.exists() or not groups.exists():
            pytest.skip("run scripts/build_database.py")
        return pd.read_parquet(links), pd.read_parquet(groups)

    def test_no_link_crosses_two_groups(self) -> None:
        links, groups = self._delivery()
        of = dict(zip(groups["record_id"], groups["signal_group_id"], strict=True))
        crossing = [
            (a, b)
            for a, b in zip(links["record_a"], links["record_b"], strict=True)
            if of.get(a) != of.get(b)
        ]
        assert crossing == []

    def test_the_correlation_links_are_the_ones_that_used_to_cross(self) -> None:
        links, _ = self._delivery()
        assert int((links["sieve"] == "correlation").sum()) == 587

    def test_the_group_carries_its_fingerprint_separately(self) -> None:
        _, groups = self._delivery()
        assert "fingerprint" in groups.columns
        assert groups["fingerprint"].nunique() == 88_196
