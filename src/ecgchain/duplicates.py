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

A link carries its scope.  Two packagings of one corpus repeating a tracing is
one finding; a single distribution shipping the same tracing twice under two
record ids is another, and the second is the one a split has to respect,
because splitting by patient does not separate a recording from its own copy.

Nothing here decides that two records are the same patient.  That is a
different question with a different answer.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "ACROSS",
    "DuplicateLink",
    "WITHIN",
    "by_digest",
    "correlate",
    "groups",
    "merge",
    "unmatched",
]

WITHIN = "within-distribution"
ACROSS = "across-distributions"


@dataclass(frozen=True)
class DuplicateLink:
    """Two records the screen says are the same recording, and how it knows."""

    record_a: str  # the lexicographically smaller id, so a pair has one form
    record_b: str
    sieve: str  # "source-file", "signal" or "correlation"
    score: float  # 1.0 for a digest match, the correlation otherwise
    scope: str  # WITHIN or ACROSS

    @staticmethod
    def between(
        first: str, second: str, sieve: str, score: float, scope: str = ACROSS
    ) -> DuplicateLink:
        a, b = sorted((first, second))
        return DuplicateLink(a, b, sieve, score, scope)


def groups(digests: Mapping[str, str | None]) -> dict[str, list[str]]:
    """Digest -> the records that carry it, in a stable order."""
    found: dict[str, list[str]] = defaultdict(list)
    for record_id, digest in digests.items():
        if digest is not None:
            found[digest].append(record_id)
    return {digest: sorted(members) for digest, members in sorted(found.items())}


def by_digest(
    digests: Mapping[str, str | None], sieve: str, source_of: Mapping[str, str]
) -> list[DuplicateLink]:
    """Link every pair of records sharing a digest, each with its scope.

    ``source_of`` maps a record id to the distribution it came from; a pair
    inside one distribution is labelled WITHIN and a pair across two is
    labelled ACROSS.  Nothing is dropped: both are findings, and they are not
    the same finding.
    """
    links: list[DuplicateLink] = []
    for members in groups(digests).values():
        if len(members) < 2:
            continue
        for index, first in enumerate(members):
            for second in members[index + 1 :]:
                scope = WITHIN if source_of.get(first) == source_of.get(second) else ACROSS
                links.append(DuplicateLink.between(first, second, sieve, 1.0, scope))
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
    targets: Mapping[str, NDArray[np.float32]],
    candidates: Iterable[tuple[str, NDArray[np.float32]]],
    threshold: float = 0.99,
    max_pairs: int = 5_000_000,
    scope: str = ACROSS,
) -> list[DuplicateLink]:
    """Best match for each target among the candidates, streamed.

    The asymmetry is the point.  ``targets`` are the records the digests left
    unmatched, and there are never many: sixty-nine for INCART, thirty-three for
    PTB, two for PTB-XL.  ``candidates`` is the whole of the other distribution,
    tens of thousands of records, and it arrives as an iterator so that one
    record is in memory at a time.  Holding both sides as dictionaries is what
    took a 15 GiB machine down.

    ``n_candidates`` is only needed for the cap; pass it when the iterator
    cannot be measured without consuming it.
    """
    best: dict[str, tuple[str, float]] = {target: ("", -1.0) for target in targets}
    seen = 0
    for candidate_id, candidate in candidates:
        seen += 1
        if len(targets) * seen > max_pairs:
            raise ValueError(
                f"{len(targets)} targets past {seen} candidates is over the "
                f"{max_pairs} cap; sieve the digests first"
            )
        for target_id, target in targets.items():
            n = min(target.size, candidate.size)
            if n < 2:
                continue
            score = float(np.corrcoef(target[:n], candidate[:n])[0, 1])
            if score > best[target_id][1]:
                best[target_id] = (candidate_id, score)
    return [
        DuplicateLink.between(target_id, match_id, "correlation", score, scope)
        for target_id, (match_id, score) in sorted(best.items())
        if match_id and score >= threshold
    ]
