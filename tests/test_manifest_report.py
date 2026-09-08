"""Every file the publishers' manifests cover, recomputed and compared."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RESULTS = Path(__file__).resolve().parents[1] / "results"
REPORT = RESULTS / "manifest_report.json"

CORRUPTED = "g3/JS13118.mat"
OBSERVED = "bbd5fe831ad2ce60dc62588a9f8eeccc2ea37564cf0bfb4d7a8d49c6a9eafdfd"


@pytest.fixture(scope="module")
def report() -> dict[str, dict]:
    if not REPORT.exists():
        pytest.skip(f"{REPORT} has not been written; run scripts/verify_manifests.py")
    return {entry["source_id"]: entry for entry in json.loads(REPORT.read_text())}


class TestTheLedger:
    def test_every_distribution_was_checked(self, report: dict[str, dict]) -> None:
        assert len(report) == 12

    def test_the_totals(self, report: dict[str, dict]) -> None:
        assert sum(e["n_declared"] for e in report.values()) == 224_883
        assert sum(e["n_checked"] for e in report.values()) == 224_882
        assert sum(e["matched"] for e in report.values()) == 224_881

    def test_the_four_outcomes_are_kept_apart(self, report: dict[str, dict]) -> None:
        for entry in report.values():
            assert entry["matched"] + len(entry["mismatched"]) == entry["n_checked"]


class TestTheOneFileThatDiffers:
    """A file the size of its neighbours whose bytes are not what was released.

    Nothing downstream would have noticed: the record reads, canonicalises and
    passes every quality check here. Only the publisher's digest catches it.
    """

    def test_ningbo_holds_it(self, report: dict[str, dict]) -> None:
        assert report["challenge-2021/ningbo"]["mismatched"] == [CORRUPTED]
        assert not report["challenge-2021/ningbo"]["holds"]

    def test_it_is_the_only_one_in_the_delivery(self, report: dict[str, dict]) -> None:
        mismatched = {
            source_id: entry["mismatched"]
            for source_id, entry in report.items()
            if entry["mismatched"]
        }
        assert mismatched == {"challenge-2021/ningbo": [CORRUPTED]}

    def test_its_record_is_still_counted(self) -> None:
        """It is in the delivery, and the report is how a reader learns that."""
        scan = json.loads((RESULTS / "record_scan.json").read_text())
        ningbo = next(e for e in scan if e["source_id"] == "challenge-2021/ningbo")
        assert ningbo["n_records"] == 34905

    def test_the_eleven_other_distributions_hold(self, report: dict[str, dict]) -> None:
        holding = {sid for sid, entry in report.items() if entry["holds"]}
        assert len(holding) == 10  # ningbo differs, cpsc_2018 is missing an entry


class TestDownloadResidue:
    def test_one_manifest_entry_is_absent_and_it_is_a_ds_store(
        self, report: dict[str, dict]
    ) -> None:
        missing = {
            source_id: entry["missing_on_disk"]
            for source_id, entry in report.items()
            if entry["missing_on_disk"]
        }
        assert missing == {"challenge-2021/cpsc_2018": [".DS_Store"]}

    def test_the_unlisted_files_are_all_fetch_residue(self, report: dict[str, dict]) -> None:
        unlisted = [name for entry in report.values() for name in entry["unlisted"]]
        assert len(unlisted) == 401
        residue = {"index.html", "robots.txt", "SHA256SUMS.txt", ".DS_Store"}
        assert {Path(name).name for name in unlisted} == residue
