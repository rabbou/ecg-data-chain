"""The label side of the delivery, as it was built on 2026-09-08."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RESULTS = Path(__file__).resolve().parents[1] / "results"
REPORT = RESULTS / "label_report.json"


@pytest.fixture(scope="module")
def report() -> dict:
    if not REPORT.exists():
        pytest.skip(f"{REPORT} has not been written; run scripts/build_labels.py")
    return json.loads(REPORT.read_text())


class TestAgainstTheOrganisersOwnCounts:
    """The reference value: thirty scored classes across eight partitions."""

    def test_every_published_cell_agrees(self, report: dict) -> None:
        comparison = report["published_comparison"]
        assert comparison["n_cells"] == 240
        assert comparison["n_agreeing"] == 240
        assert comparison["n_disagreements"] == 0
        assert comparison["disagreements"] == []

    def test_all_eight_partitions_were_checked(self, report: dict) -> None:
        assert len(report["partitions_checked"]) == 8
        assert report["n_scored_classes"] == 30


class TestPatients:
    def test_only_two_distributions_publish_a_patient_key(self, report: dict) -> None:
        assert report["patients_by_source"] == {
            "physionet/ptb-xl": 18869,
            "physionet/ptbdb": 290,
        }
        assert report["n_patients"] == 19159

    def test_the_ten_others_are_named_as_publishing_none(self, report: dict) -> None:
        """Ten silent distributions, reported rather than given one patient per record."""
        silent = report["distributions_publishing_no_patient_key"]
        assert len(silent) == 10
        assert "challenge-2021/ptb-xl" in silent
        assert "physionet/ptb-xl" not in silent


class TestTheCodeTables:
    def test_the_three_published_tables_are_all_read(self, report: dict) -> None:
        assert report["label_map_by_source"] == {
            "ptbxlToSNOMED.csv": 111,
            "dx_mapping_scored.csv": 30,
            "AHA_SNOMED_mapping.csv": 23,
        }
        assert report["n_label_map_rows"] == 164


class TestPropagation:
    def test_the_silent_distributions_get_their_statements_from_their_twins(
        self, report: dict
    ) -> None:
        assert report["propagated_by_source"] == {
            "physionet/ptb-xl": 56049,
            "physionet/ptbdb": 590,
            "physionet/incartdb": 229,
        }
        assert report["n_propagated_label_rows"] == 56868
        assert report["n_records_given_a_propagated_label"] == 22389

    def test_ludb_gets_nothing_because_it_arrives_once(self, report: dict) -> None:
        assert "physionet/ludb" not in report["propagated_by_source"]

    def test_two_tables_stay_empty_until_something_reads_them(self, report: dict) -> None:
        assert report["deferred_tables"] == ["split", "signal_window"]


class TestTheTwoRoutesToTheSameJoin:
    """The naming convention is an answer independent of the signal screen."""

    def test_the_named_join_matches_every_original_record(self, report: dict) -> None:
        join = report["ptbxl_named_join"]
        assert join["n_original"] == 21799
        assert join["n_matched_by_name"] == 21799
        assert join["n_original_without_a_named_twin"] == 0

    def test_it_leaves_exactly_the_thirty_eight_the_screen_explained(self, report: dict) -> None:
        """36 records the bundle repeats inside itself, plus 2 near-duplicates."""
        join = report["ptbxl_named_join"]
        assert join["n_bundled"] - join["n_original"] == 38
        assert join["n_bundled_not_named_by_any_original"] == 38
