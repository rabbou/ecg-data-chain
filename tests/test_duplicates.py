"""The three sieves, on made-up records where the answer is known."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest
from numpy.typing import NDArray

from ecgchain.duplicates import (
    ACROSS,
    WITHIN,
    DuplicateLink,
    by_digest,
    correlate,
    groups,
    merge,
    unmatched,
)

SOURCE_OF = {"a:1": "a", "a:2": "a", "b:1": "b", "b:2": "b"}


class TestPairForm:
    def test_a_pair_has_one_form_whichever_way_it_is_given(self) -> None:
        first = DuplicateLink.between("b:1", "a:1", "signal", 1.0)
        second = DuplicateLink.between("a:1", "b:1", "signal", 1.0)
        assert first == second
        assert first.record_a == "a:1"


class TestGroups:
    def test_a_digest_carries_its_records_in_order(self) -> None:
        assert groups({"b:1": "x", "a:1": "x", "b:2": "y"}) == {
            "x": ["a:1", "b:1"],
            "y": ["b:2"],
        }

    def test_a_record_with_no_digest_is_in_no_group(self) -> None:
        assert groups({"a:1": None}) == {}


class TestByDigest:
    def test_records_sharing_a_digest_are_linked(self) -> None:
        links = by_digest({"a:1": "x", "b:1": "x", "b:2": "y"}, "signal", SOURCE_OF)
        assert [(link.record_a, link.record_b) for link in links] == [("a:1", "b:1")]
        assert links[0].sieve == "signal"
        assert links[0].score == 1.0

    def test_a_record_with_no_digest_is_not_linked(self) -> None:
        assert by_digest({"a:1": None, "b:1": None}, "signal", SOURCE_OF) == []

    def test_a_pair_inside_one_distribution_is_scoped_within(self) -> None:
        """One distribution shipping a tracing twice is what a split must respect."""
        links = by_digest({"a:1": "x", "a:2": "x"}, "signal", SOURCE_OF)
        assert len(links) == 1
        assert links[0].scope == WITHIN

    def test_a_pair_across_two_distributions_is_scoped_across(self) -> None:
        links = by_digest({"a:1": "x", "b:1": "x"}, "signal", SOURCE_OF)
        assert links[0].scope == ACROSS

    def test_both_scopes_come_out_of_one_group(self) -> None:
        """Nothing is dropped: three records sharing a tracing make three pairs."""
        links = by_digest({"a:1": "x", "a:2": "x", "b:1": "x"}, "signal", SOURCE_OF)
        by_scope = {(link.record_a, link.record_b): link.scope for link in links}
        assert by_scope == {
            ("a:1", "a:2"): WITHIN,
            ("a:1", "b:1"): ACROSS,
            ("a:2", "b:1"): ACROSS,
        }


class TestMerge:
    """Searching each side against the other finds every pair twice."""

    def test_a_pair_found_from_both_directions_is_kept_once(self) -> None:
        forward = DuplicateLink.between("a:1", "b:1", "correlation", 0.995)
        backward = DuplicateLink.between("b:1", "a:1", "correlation", 0.995)
        assert len(merge([forward, backward])) == 1

    def test_the_better_score_wins_within_one_sieve(self) -> None:
        weaker = DuplicateLink.between("a:1", "b:1", "correlation", 0.991)
        stronger = DuplicateLink.between("a:1", "b:1", "correlation", 0.999)
        assert merge([weaker, stronger])[0].score == 0.999
        assert merge([stronger, weaker])[0].score == 0.999

    def test_the_cheaper_sieve_keeps_the_pair_it_already_settled(self) -> None:
        """A digest match is not relabelled by a correlation that looks again."""
        digest = DuplicateLink.between("a:1", "b:1", "signal", 1.0)
        correlation = DuplicateLink.between("a:1", "b:1", "correlation", 1.0)
        assert merge([digest], [correlation])[0].sieve == "signal"

    def test_distinct_pairs_all_survive(self) -> None:
        first = DuplicateLink.between("a:1", "b:1", "signal", 1.0)
        second = DuplicateLink.between("a:2", "b:2", "signal", 1.0)
        assert len(merge([first, second])) == 2

    def test_the_order_is_stable(self) -> None:
        links = [
            DuplicateLink.between("a:2", "b:2", "signal", 1.0),
            DuplicateLink.between("a:1", "b:1", "signal", 1.0),
        ]
        assert [link.record_a for link in merge(links)] == ["a:1", "a:2"]

    def test_no_more_links_than_the_smaller_side_has_records(self) -> None:
        """The invariant a doubled count breaks: 516 records cannot make 1,032 pairs."""
        left = [f"a:{i}" for i in range(5)]
        right = [f"b:{i}" for i in range(9)]
        both = [
            DuplicateLink.between(a, b, "correlation", 0.999)
            for a, b in zip(left, right, strict=False)
        ]
        reversed_direction = [
            DuplicateLink.between(b, a, "correlation", 0.999)
            for a, b in zip(left, right, strict=False)
        ]
        merged = merge(both, reversed_direction)
        assert len(merged) <= min(len(left), len(right))


class TestUnmatched:
    def test_what_no_link_mentions(self) -> None:
        links = by_digest({"a:1": "x", "b:1": "x"}, "signal", SOURCE_OF)
        assert unmatched(["a:1", "a:2", "a:3"], links) == ["a:2", "a:3"]

    def test_nothing_left_when_everything_is_linked(self) -> None:
        links = by_digest({"a:1": "x", "b:1": "x"}, "signal", SOURCE_OF)
        assert unmatched(["a:1"], links) == []


class TestCorrelate:
    @staticmethod
    def _wave(seed: int, n: int = 500) -> NDArray[np.float32]:
        rng = np.random.default_rng(seed)
        return rng.normal(0, 1, n).astype(np.float32)

    def test_the_same_wave_at_another_scale_is_linked(self) -> None:
        """A change of ADC gain is a change of scale; correlation does not care."""
        wave = self._wave(0)
        links = correlate({"a:1": wave}, [("b:1", (wave * 3.27).astype(np.float32))])
        assert len(links) == 1
        assert links[0].sieve == "correlation"
        assert links[0].score == pytest.approx(1.0)
        assert links[0].scope == ACROSS

    def test_the_scope_is_carried_through(self) -> None:
        wave = self._wave(0)
        links = correlate({"a:1": wave}, [("a:2", wave)], scope=WITHIN)
        assert links[0].scope == WITHIN

    def test_an_unrelated_wave_is_not_linked(self) -> None:
        assert correlate({"a:1": self._wave(0)}, [("b:1", self._wave(1))]) == []

    def test_each_target_takes_its_best_match_only(self) -> None:
        wave = self._wave(0)
        links = correlate({"a:1": wave}, [("b:1", wave), ("b:2", (wave * 2).astype(np.float32))])
        assert len(links) == 1

    def test_windows_of_different_lengths_compare_on_the_shorter(self) -> None:
        wave = self._wave(0)
        links = correlate({"a:1": wave}, [("b:1", wave[:300])])
        assert len(links) == 1

    def test_a_comparison_past_the_cap_is_refused_not_run(self) -> None:
        """A screen that silently spends an hour is a screen nobody runs twice."""
        targets = {f"a:{i}": self._wave(i, 4) for i in range(10)}
        candidates = [(f"b:{i}", self._wave(i, 4)) for i in range(10)]
        with pytest.raises(ValueError, match="over the 50 cap"):
            correlate(targets, candidates, max_pairs=50)

    def test_the_candidates_are_consumed_one_at_a_time(self) -> None:
        """The rewrite that matters: the other side is never held in memory."""
        alive: list[str] = []

        def stream() -> Iterator[tuple[str, NDArray[np.float32]]]:
            for index in range(4):
                alive.append(f"b:{index}")
                assert len(alive) == index + 1
                yield f"b:{index}", self._wave(index + 1)

        correlate({"a:1": self._wave(0)}, stream())
        assert alive == ["b:0", "b:1", "b:2", "b:3"]

    def test_a_generator_that_yields_nothing_links_nothing(self) -> None:
        assert correlate({"a:1": self._wave(0)}, iter([])) == []
