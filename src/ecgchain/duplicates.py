"""Finding the same tracing twice, cheapest question first.

Three sieves, in this order, because each one is orders of magnitude dearer
than the one before it and each one shrinks the work the next has to do.

1. The source file.  Two records whose signal files carry the same SHA-256 --
   the publisher's, not ours -- are the same bytes.  Free: the digests are
   already in the manifests.
2. The canonical signal.  Two records whose first ten seconds of twelve leads
   agree to ten microvolts are the same recording, whatever the file says.
   This is what catches a repackaging that renamed the records and changed the
   ADC gain.
3. Correlation.  What is left after the first two, pair by pair.  Quadratic,
   so it runs on leftovers only and refuses a comparison it cannot afford
   rather than quietly taking an hour.

Nothing here decides that two records are the same patient.  That is a
different question with a different answer, and it is the one the splits
depend on.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

__all__ = ["DuplicateLink", "by_digest", "correlate", "merge", "unmatched"]


@dataclass(frozen=True)
class DuplicateLink:
    """Two records the screen says are the same recording, and how it knows."""

    record_a: str  # the lexicographically smaller id, so a pair has one form
    record_b: str
    sieve: str  # "source-file", "signal" or "correlation"
    score: float  # 1.0 for a digest match, the correlation otherwise

    @staticmethod
    def between(first: str, second: str, sieve: str, score: float) -> DuplicateLink:
        a, b = sorted((first, second))
        return DuplicateLink(a, b, sieve, score)


def by_digest(
    digests: Mapping[str, str | None], sieve: str, within: Mapping[str, str] | None = None
) -> list[DuplicateLink]:
    """Link every pair of records sharing a digest.

    ``within`` maps a record id to its distribution; when given, two records of
    the same distribution are not linked, because a corpus repeating a tracing
    inside itself is a different finding from two packagings of one corpus.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for record_id, digest in digests.items():
        if digest is not None:
            groups[digest].append(record_id)
    links: list[DuplicateLink] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ordered = sorted(members)
        for index, first in enumerate(ordered):
            for second in ordered[index + 1 :]:
                if within is not None and within.get(first) == within.get(second):
                    continue
                links.append(DuplicateLink.between(first, second, sieve, 1.0))
    return links


def merge(*groups: Iterable[DuplicateLink]) -> list[DuplicateLink]:
    """One link per pair of records, in sieve order.

    Groups are given cheapest sieve first and the first group that holds a pair
    wins it: a pair the file digests already settled is not relabelled by a
    correlation that happens to look at it again.  Within a group the better
    score wins, which matters for correlation, where searching each side against
    the other finds every pair twice.
    """
    best: dict[tuple[str, str], DuplicateLink] = {}
    for group in groups:
        for link in group:
            key = (link.record_a, link.record_b)
            held = best.get(key)
            if held is None or (held.sieve == link.sieve and link.score > held.score):
                best[key] = link
    return sorted(best.values(), key=lambda link: (link.record_a, link.record_b))


def unmatched(record_ids: Iterable[str], links: Iterable[DuplicateLink]) -> list[str]:
    """The records no link mentions, in a stable order."""
    linked = {record for link in links for record in (link.record_a, link.record_b)}
    return sorted(set(record_ids) - linked)


def correlate(
    left: Mapping[str, NDArray[np.float32]],
    right: Mapping[str, NDArray[np.float32]],
    threshold: float = 0.99,
    max_pairs: int = 5_000_000,
) -> list[DuplicateLink]:
    """Best-match links between two sets of single-lead windows.

    Raises rather than running when the comparison is larger than ``max_pairs``:
    a screen that silently spends an hour is a screen nobody runs twice.
    """
    pairs = len(left) * len(right)
    if pairs > max_pairs:
        raise ValueError(f"{pairs} pairs is past the {max_pairs} cap; sieve the digests first")
    links: list[DuplicateLink] = []
    for left_id, left_window in left.items():
        best_id, best_score = "", -1.0
        for right_id, right_window in right.items():
            n = min(left_window.size, right_window.size)
            if n < 2:
                continue
            score = float(np.corrcoef(left_window[:n], right_window[:n])[0, 1])
            if score > best_score:
                best_id, best_score = right_id, score
        if best_id and best_score >= threshold:
            links.append(DuplicateLink.between(left_id, best_id, "correlation", best_score))
    return links
