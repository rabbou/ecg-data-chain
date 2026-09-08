"""The committed scan, against counts taken from the corpora another way.

The numbers on the right-hand side were counted with ``find -name '*.hea'`` on
2026-09-08, not produced by this package. A scan that drifts from them is
wrong, and the test says so without needing the corpora present.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RESULTS = Path(__file__).resolve().parents[1] / "results"
SCAN = RESULTS / "record_scan.json"

# source id -> (records, leads per record, unit spellings the header text carries)
# An empty list means the header names no units at all and a reader that
# reports "mV" for these records is speaking for the file, not quoting it.
COUNTED = {
    "challenge-2021/chapman_shaoxing": (10247, [12], ["mV"]),
    "challenge-2021/cpsc_2018": (6877, [12], ["mV"]),
    "challenge-2021/cpsc_2018_extra": (3453, [12], ["mV"]),
    "challenge-2021/georgia": (10344, [12], ["mV"]),
    "challenge-2021/ningbo": (34905, [12], ["mV"]),
    "challenge-2021/ptb": (516, [12], ["mv"]),
    "challenge-2021/ptb-xl": (21837, [12], ["mv"]),
    "challenge-2021/st_petersburg_incart": (74, [12], ["mv"]),
    "physionet/incartdb": (75, [12], []),
    "physionet/ptb-xl": (21837 - 38, [12], ["mV"]),
    "physionet/ludb": (200, [12], ["mV"]),
    "physionet/ptbdb": (549, [15], []),
}

# The two distributions that name no units, and the two that spell it in lower
# case. Both facts are about the files, not about this package.
DECLARE_NO_UNITS = {"physionet/incartdb", "physionet/ptbdb"}
SPELL_IT_LOWER_CASE = {
    "challenge-2021/ptb",
    "challenge-2021/ptb-xl",
    "challenge-2021/st_petersburg_incart",
}

CHALLENGE_TRAINING_RECORDS = 88_253  # the published size of the 2021 training set


@pytest.fixture(scope="module")
def scan() -> dict[str, dict]:
    if not SCAN.exists():
        pytest.skip(f"{SCAN} has not been written; run scripts/scan_records.py")
    return {entry["source_id"]: entry for entry in json.loads(SCAN.read_text())}


class TestTheCommittedScan:
    def test_every_source_is_there(self, scan: dict[str, dict]) -> None:
        assert set(scan) == set(COUNTED)

    @pytest.mark.parametrize("source_id", sorted(COUNTED))
    def test_record_count(self, scan: dict[str, dict], source_id: str) -> None:
        assert scan[source_id]["n_records"] == COUNTED[source_id][0]

    @pytest.mark.parametrize("source_id", sorted(COUNTED))
    def test_leads_per_record(self, scan: dict[str, dict], source_id: str) -> None:
        assert scan[source_id]["leads_per_record"] == COUNTED[source_id][1]

    @pytest.mark.parametrize("source_id", sorted(COUNTED))
    def test_declared_unit_spellings(self, scan: dict[str, dict], source_id: str) -> None:
        assert sorted(scan[source_id]["units_declared"]) == COUNTED[source_id][2]

    def test_one_lead_row_per_channel(self, scan: dict[str, dict]) -> None:
        for source_id, entry in scan.items():
            expected = entry["n_records"] * COUNTED[source_id][1][0]
            assert entry["n_leads_rows"] == expected

    def test_the_bundle_holds_the_published_training_size(self, scan: dict[str, dict]) -> None:
        bundle = sum(
            entry["n_records"]
            for entry in scan.values()
            if entry["distribution"] == "challenge-2021"
        )
        assert bundle == CHALLENGE_TRAINING_RECORDS


class TestWhatTheScanShowsAboutTheCorpora:
    def test_three_sources_spell_the_unit_in_lower_case(self, scan: dict[str, dict]) -> None:
        """A case-sensitive millivolt check would reject 22,427 of the bundle's records."""
        lower = {sid for sid, entry in scan.items() if list(entry["units_declared"]) == ["mv"]}
        assert lower == SPELL_IT_LOWER_CASE
        assert sum(scan[sid]["n_records"] for sid in lower) == 22_427

    def test_two_distributions_name_no_units_at_all(self, scan: dict[str, dict]) -> None:
        """Their signal lines stop at the gain; wfdb supplies mV on their behalf."""
        silent = {sid for sid, entry in scan.items() if entry["n_units_declared"] == 0}
        assert silent == DECLARE_NO_UNITS
        for source_id in silent:
            assert scan[source_id]["units_declared"] == {}
            assert scan[source_id]["n_all_millivolts"] == 0

    def test_every_record_that_names_its_units_names_millivolts(
        self, scan: dict[str, dict]
    ) -> None:
        for source_id, entry in scan.items():
            if source_id in DECLARE_NO_UNITS:
                continue
            assert entry["n_units_declared"] == entry["n_records"]
            assert entry["n_all_millivolts"] == entry["n_records"]

    def test_only_ptb_ships_channels_outside_the_twelve(self, scan: dict[str, dict]) -> None:
        """PTB's three Frank leads, on 549 records, and nowhere else."""
        with_extra = {sid for sid, e in scan.items() if e["n_non_canonical_leads"]}
        assert with_extra == {"physionet/ptbdb"}
        assert scan["physionet/ptbdb"]["n_non_canonical_leads"] == 549 * 3

    def test_the_same_corpus_disagrees_with_itself_across_packagings(
        self, scan: dict[str, dict]
    ) -> None:
        """PTB: 549 records of 15 channels here, 516 of 12 there."""
        standalone, bundled = scan["physionet/ptbdb"], scan["challenge-2021/ptb"]
        assert standalone["corpus"] == bundled["corpus"] == "ptb"
        assert standalone["n_records"] != bundled["n_records"]
        assert standalone["leads_per_record"] != bundled["leads_per_record"]

    def test_the_bundle_holds_thirty_eight_ptbxl_records_physionet_does_not(
        self, scan: dict[str, dict]
    ) -> None:
        bundled = scan["challenge-2021/ptb-xl"]["n_records"]
        standalone = scan["physionet/ptb-xl"]["n_records"]
        assert bundled - standalone == 38

    def test_the_snomed_labels_are_already_in_the_bundle_headers(
        self, scan: dict[str, dict]
    ) -> None:
        bundle = [e for e in scan.values() if e["distribution"] == "challenge-2021"]
        assert all(e["n_with_dx"] == e["n_records"] for e in bundle)
        standalone = [e for e in scan.values() if e["distribution"] == "physionet"]
        assert all(e["n_with_dx"] == 0 for e in standalone)
