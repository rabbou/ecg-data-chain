"""The committed screen: what each corpus that arrives twice actually holds.

The three corpora on the box that come in two packagings are the only place
where the catalogue's key can be checked against reality rather than argued
for. Every number here was produced on 2026-09-08 by reading the signals.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RESULTS = Path(__file__).resolve().parents[1] / "results"
SCREEN = RESULTS / "duplicate_scan.json"


# source id -> (pairs, groups, distinct tracings) inside that one distribution
REPEATS_WITHIN = {
    "challenge-2021/chapman_shaoxing": (13, 13, 10234),
    "challenge-2021/cpsc_2018": (261, 250, 6622),
    "challenge-2021/cpsc_2018_extra": (70, 68, 3384),
    "challenge-2021/georgia": (96, 92, 10250),
    "challenge-2021/ningbo": (3, 3, 34902),
    "challenge-2021/ptb-xl": (38, 34, 21801),
}


@pytest.fixture(scope="module")
def scan() -> dict:
    if not SCREEN.exists():
        pytest.skip(f"{SCREEN} has not been written; run scripts/scan_quality.py")
    return json.loads(SCREEN.read_text())


@pytest.fixture(scope="module")
def screen(scan: dict) -> dict[str, dict]:
    return {entry["corpus"]: entry for entry in scan["across"]}


@pytest.fixture(scope="module")
def inside(scan: dict) -> dict[str, dict]:
    return {entry["source_id"]: entry for entry in scan["within"]}


class TestWhatEachDistributionRepeatsInsideItself:
    """The scope a split has to respect, and the one nobody had counted.

    Splitting by patient does not separate a recording from its own copy under
    another record id, so these are the pairs that decide whether a fold is
    honest. Every pair opened in the copy check was identical sample for
    sample, so they are copies rather than second acquisitions.
    """

    def test_every_distribution_is_reported(self, inside: dict[str, dict]) -> None:
        assert len(inside) == 12

    @pytest.mark.parametrize("source_id", sorted(REPEATS_WITHIN))
    def test_pairs_groups_and_distinct_tracings(
        self, inside: dict[str, dict], source_id: str
    ) -> None:
        entry = inside[source_id]
        pairs, groups, distinct = REPEATS_WITHIN[source_id]
        assert entry["n_pairs"] == pairs
        assert entry["n_groups"] == groups
        assert entry["n_distinct_tracings"] == distinct

    def test_the_six_others_repeat_nothing(self, inside: dict[str, dict]) -> None:
        silent = {sid for sid, entry in inside.items() if entry["n_pairs"] == 0}
        assert silent == set(inside) - set(REPEATS_WITHIN)

    def test_no_physionet_distribution_repeats_anything(self, inside: dict[str, dict]) -> None:
        """The repackaging introduced every one of them."""
        originals = {sid: e for sid, e in inside.items() if sid.startswith("physionet/")}
        assert len(originals) == 4
        assert all(entry["n_pairs"] == 0 for entry in originals.values())

    def test_a_group_can_hold_more_than_two_records(self, inside: dict[str, dict]) -> None:
        """250 groups make 261 pairs, so some tracings arrived three times."""
        entry = inside["challenge-2021/cpsc_2018"]
        assert entry["n_pairs"] > entry["n_groups"]
        assert entry["largest_group"] >= 3


class TestTheShapeOfTheScreen:
    def test_three_corpora_arrive_twice(self, screen: dict[str, dict]) -> None:
        assert set(screen) == {"incart", "ptb", "ptb-xl"}

    @pytest.mark.parametrize("corpus", ["incart", "ptb", "ptb-xl"])
    def test_every_bundled_record_takes_exactly_one_link(
        self, screen: dict[str, dict], corpus: str
    ) -> None:
        """The invariant a doubled count breaks.

        Searching each side against the other finds every pair twice, so the
        screen has to keep each pair once. The matching is not one to one --
        thirty-six of PTB-XL's bundled records point at an original that another
        bundled record already claimed -- so the count that must come out exact
        is on the bundle's side, not the original's.
        """
        entry = screen[corpus]
        bundled = next(sid for sid in entry["n_records"] if sid.startswith("challenge-2021/"))
        matched = entry["n_records"][bundled] - len(entry["unmatched"][bundled])
        assert entry["n_linked_pairs"] == matched

    @pytest.mark.parametrize("corpus", ["incart", "ptb", "ptb-xl"])
    def test_the_sieves_account_for_every_link(self, screen: dict[str, dict], corpus: str) -> None:
        entry = screen[corpus]
        assert (
            entry["linked_by_source_file"]
            + entry["linked_by_signal"]
            + entry["linked_by_correlation"]
            == entry["n_linked_pairs"]
        )

    @pytest.mark.parametrize("corpus", ["incart", "ptb", "ptb-xl"])
    def test_not_one_native_record_id_is_shared(self, screen: dict[str, dict], corpus: str) -> None:
        """Every repackaging renamed every record. Id-based dedup sees nothing."""
        assert screen[corpus]["shared_native_ids"] == []

    def test_no_screen_was_refused_for_size(self, screen: dict[str, dict]) -> None:
        assert all(entry["note"] == "" for entry in screen.values())


class TestIncart:
    """Seventy-five records at PhysioNet, seventy-four in the bundle."""

    def test_every_bundled_record_is_matched(self, screen: dict[str, dict]) -> None:
        entry = screen["incart"]
        assert entry["n_linked_pairs"] == 74
        assert entry["unmatched"]["challenge-2021/st_petersburg_incart"] == []

    def test_one_record_did_not_survive_the_repackaging(self, screen: dict[str, dict]) -> None:
        assert screen["incart"]["unmatched"]["physionet/incartdb"] == ["physionet/incartdb:I36"]

    def test_the_fingerprint_alone_finds_only_five_of_them(self, screen: dict[str, dict]) -> None:
        """The gain went from 306 to 1000 units per millivolt.

        Requantising moves every sample that sat on a rounding boundary, so the
        quantised digest catches five pairs and correlation catches the other
        sixty-nine. This is the number that says why the third sieve exists.
        """
        entry = screen["incart"]
        assert entry["linked_by_signal"] == 5
        assert entry["linked_by_correlation"] == 69


class TestPtb:
    def test_every_bundled_record_is_matched(self, screen: dict[str, dict]) -> None:
        entry = screen["ptb"]
        assert entry["n_linked_pairs"] == 516
        assert entry["unmatched"]["challenge-2021/ptb"] == []

    def test_thirty_three_records_are_only_in_the_original(self, screen: dict[str, dict]) -> None:
        assert len(screen["ptb"]["unmatched"]["physionet/ptbdb"]) == 33
        assert 549 - 516 == 33

    def test_the_fingerprint_finds_none_of_them(self, screen: dict[str, dict]) -> None:
        """The original ships fifteen channels, no unit string and another gain."""
        assert screen["ptb"]["linked_by_signal"] == 0
        assert screen["ptb"]["linked_by_correlation"] == 516


class TestPtbxl:
    """Where the thirty-eight extra records of the bundle actually go."""

    def test_every_record_on_both_sides_is_matched(self, screen: dict[str, dict]) -> None:
        entry = screen["ptb-xl"]
        assert entry["unmatched"]["challenge-2021/ptb-xl"] == []
        assert entry["unmatched"]["physionet/ptb-xl"] == []

    def test_the_bundle_holds_more_links_than_the_original_has_records(
        self, screen: dict[str, dict]
    ) -> None:
        """21,837 links for 21,799 original records: the surplus is repetition.

        Thirty-six of the bundle's extra records repeat a tracing already in the
        bundle, and the last two are near-duplicates the digest missed and
        correlation caught. Thirty-six plus two is the thirty-eight.
        """
        entry = screen["ptb-xl"]
        assert entry["n_linked_pairs"] == 21_837
        assert entry["n_records"]["challenge-2021/ptb-xl"] == 21_837
        assert entry["n_records"]["physionet/ptb-xl"] == 21_799
        assert entry["linked_by_signal"] == 21_835
        assert entry["linked_by_correlation"] == 2
        assert 21_837 - 21_799 == 36 + 2

    def test_the_source_file_sieve_never_fires(self, screen: dict[str, dict]) -> None:
        """No repackaging on this box preserved a single byte of a signal file."""
        assert all(entry["linked_by_source_file"] == 0 for entry in screen.values())
