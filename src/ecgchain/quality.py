"""What is wrong with a tracing, and a fingerprint of what it contains.

Both come out of one read of the signal, because reading 110,876 records twice
would double the only genuinely expensive pass in the chain.

The fingerprint is a digest of the first ten seconds of the twelve standard
leads, in millivolts, quantised to ten microvolts.  The quantisation is not
sloppiness: the same tracing reaches the box at different ADC gains.  INCART's
PhysioNet packaging carries twelve distinct gains from 240 to 1063 units per
millivolt, varying by record and by lead, where the Challenge repackaging
rescales every record to 1000; PTB goes from 2000 to 1000 the same way.  A
digest of the raw samples would call two copies of one recording different,
which is the opposite of what a duplicate screen is for.  Ten microvolts is
above the coarsest of those steps and far below anything an electrocardiogram
is read at.

The three faults flagged here are the ones that make a record unusable rather
than merely noisy: a lead that is not there, a lead that never moves, and a
lead pinned to its own extreme.  A signal quality index belongs on top of these,
not instead of them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import wfdb
from numpy.typing import NDArray

from .ingest import CANONICAL_LEADS
from .sources import Source

__all__ = [
    "MICROVOLTS_PER_STEP",
    "QualityRow",
    "SATURATION_SHARE",
    "WINDOW_SECONDS",
    "canonical_window",
    "quality_row",
    "signal_digest",
]

WINDOW_SECONDS = 10.0  # what every corpus here holds at least once
MICROVOLTS_PER_STEP = 10.0  # the digest's quantum
SATURATION_SHARE = 0.01  # a lead pinned to its extreme for one per cent of the window


@dataclass(frozen=True)
class QualityRow:
    """One tracing, judged."""

    record_id: str
    missing_leads: tuple[str, ...]
    flat_leads: tuple[str, ...]
    saturated_leads: tuple[str, ...]
    n_nonfinite: int
    n_samples_read: int
    signal_digest: str | None  # None when a canonical lead is missing

    @property
    def holds(self) -> bool:
        return not (
            self.missing_leads or self.flat_leads or self.saturated_leads or self.n_nonfinite
        )


def canonical_window(
    signal: NDArray[np.float64], lead_names: list[str], sampling_rate_hz: float
) -> tuple[NDArray[np.float32] | None, tuple[str, ...]]:
    """The first ten seconds of the twelve standard leads, in canonical order.

    Returns ``None`` and the names of the missing leads when the record does not
    carry all twelve; PTB's three Frank leads are dropped rather than refused.
    """
    by_upper = {name.strip().upper(): position for position, name in enumerate(lead_names)}
    missing = tuple(name for name in CANONICAL_LEADS if name.upper() not in by_upper)
    if missing:
        return None, missing
    order = [by_upper[name.upper()] for name in CANONICAL_LEADS]
    n = min(int(round(WINDOW_SECONDS * sampling_rate_hz)), signal.shape[0])
    return np.ascontiguousarray(signal[:n, order].T, dtype=np.float32), ()


def signal_digest(window: NDArray[np.float32]) -> str:
    """A digest of the window, quantised so two gains of one recording agree.

    A sample that is not finite becomes the smallest representable step rather
    than zero: a gap and a flat line at zero millivolts are different things
    and the digest must not confuse them.
    """
    scaled = window * (1000.0 / MICROVOLTS_PER_STEP)
    steps = np.where(np.isfinite(scaled), np.rint(scaled), np.iinfo(np.int32).min).astype(np.int32)
    return hashlib.sha256(steps.tobytes()).hexdigest()


def _faults(window: NDArray[np.float32]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    flat: list[str] = []
    saturated: list[str] = []
    for name, lead in zip(CANONICAL_LEADS, window, strict=True):
        finite = lead[np.isfinite(lead)]
        if finite.size == 0 or float(finite.min()) == float(finite.max()):
            flat.append(name)
            continue
        at_edge = np.count_nonzero(finite == finite.min()) + np.count_nonzero(
            finite == finite.max()
        )
        if at_edge >= SATURATION_SHARE * finite.size:
            saturated.append(name)
    return tuple(flat), tuple(saturated)


def quality_row(source: Source, header: Path) -> QualityRow:
    """Read one record and judge it."""
    record_id = f"{source.source_id}:{header.stem}"
    meta: Any = wfdb.rdrecord(str(header.with_suffix("")))
    signal = np.asarray(meta.p_signal, dtype=np.float64)
    window, missing = canonical_window(signal, list(meta.sig_name), float(meta.fs))
    if window is None:
        return QualityRow(record_id, missing, (), (), 0, 0, None)
    flat, saturated = _faults(window)
    return QualityRow(
        record_id=record_id,
        missing_leads=(),
        flat_leads=flat,
        saturated_leads=saturated,
        n_nonfinite=int(np.count_nonzero(~np.isfinite(window))),
        n_samples_read=int(window.shape[1]),
        signal_digest=signal_digest(window),
    )
