"""Judging a tracing, and fingerprinting it so two packagings agree."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ecgchain.ingest import CANONICAL_LEADS
from ecgchain.quality import (
    MICROVOLTS_PER_STEP,
    SATURATION_SHARE,
    canonical_window,
    signal_digest,
)

RATE = 500.0
LENGTH = 5000


def _signal(n_samples: int = LENGTH, n_leads: int = 12, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0, 0.5, size=(n_samples, n_leads))


class TestTheCanonicalWindow:
    def test_leads_come_back_in_canonical_order(self) -> None:
        shuffled = list(reversed(CANONICAL_LEADS))
        window, missing = canonical_window(_signal(), shuffled, RATE)
        assert missing == ()
        assert window is not None
        assert window.shape == (12, LENGTH)

    def test_case_does_not_decide_the_lead(self) -> None:
        lower = [name.lower() for name in CANONICAL_LEADS]
        window, missing = canonical_window(_signal(), lower, RATE)
        assert missing == ()
        assert window is not None

    def test_the_frank_leads_are_dropped_not_refused(self) -> None:
        """PTB ships fifteen channels; the twelve standard ones are the window."""
        names = [*CANONICAL_LEADS, "vx", "vy", "vz"]
        window, missing = canonical_window(_signal(n_leads=15), names, RATE)
        assert missing == ()
        assert window is not None
        assert window.shape[0] == 12

    def test_a_missing_lead_is_named_and_no_window_is_returned(self) -> None:
        names = [*CANONICAL_LEADS[:11], "vx"]
        window, missing = canonical_window(_signal(), names, RATE)
        assert window is None
        assert missing == ("V6",)

    def test_the_window_is_ten_seconds(self) -> None:
        window, _ = canonical_window(_signal(n_samples=462_600), list(CANONICAL_LEADS), 257.0)
        assert window is not None
        assert window.shape[1] == 2570

    def test_a_short_record_is_not_padded(self) -> None:
        window, _ = canonical_window(_signal(n_samples=1000), list(CANONICAL_LEADS), RATE)
        assert window is not None
        assert window.shape[1] == 1000


class TestTheFingerprint:
    @staticmethod
    def _window(seed: int = 0) -> NDArray[np.float32]:
        window, _ = canonical_window(_signal(seed=seed), list(CANONICAL_LEADS), RATE)
        assert window is not None
        return window

    def test_the_same_signal_gives_the_same_digest(self) -> None:
        assert signal_digest(self._window()) == signal_digest(self._window())

    def test_a_different_signal_gives_a_different_digest(self) -> None:
        assert signal_digest(self._window(0)) != signal_digest(self._window(1))

    def test_a_nudge_that_rounds_back_to_the_same_step_does_not_show(self) -> None:
        """The point of the quantum: two ADC gains of one recording can agree."""
        step = MICROVOLTS_PER_STEP / 1000.0
        on_grid = (np.rint(self._window() / step) * step).astype(np.float32)
        assert signal_digest((on_grid + step * 0.2).astype(np.float32)) == signal_digest(on_grid)

    def test_a_nudge_across_a_rounding_boundary_does_show(self) -> None:
        """And the reason the screen cannot stop at this sieve.

        A sub-quantum difference still moves any sample sitting on a rounding
        boundary, so two gains of one recording agree here only sometimes. On
        the box that is 5 of INCART's 74 pairs; the other 69 need correlation.
        """
        step = MICROVOLTS_PER_STEP / 1000.0
        on_boundary = np.full((12, 100), step * 0.5, dtype=np.float32)
        assert signal_digest((on_boundary + step * 0.2).astype(np.float32)) != signal_digest(
            on_boundary
        )

    def test_a_difference_above_the_quantum_does_show(self) -> None:
        window = self._window()
        moved = (window + (MICROVOLTS_PER_STEP / 1000.0) * 3).astype(np.float32)
        assert signal_digest(moved) != signal_digest(window)

    def test_a_gap_is_not_a_flat_line_at_zero(self) -> None:
        """A record with NaN must not hash as one sitting at zero millivolts."""
        gap = self._window().copy()
        zero = gap.copy()
        gap[0, :10] = np.nan
        zero[0, :10] = 0.0
        assert signal_digest(gap) != signal_digest(zero)


class TestFaults:
    @staticmethod
    def _row(window: np.ndarray) -> tuple[tuple[str, ...], tuple[str, ...]]:
        from ecgchain.quality import _faults

        return _faults(window.astype(np.float32))

    def test_a_constant_lead_is_flat(self) -> None:
        window = _signal().T.copy()
        window[3, :] = 0.7
        flat, _ = self._row(window)
        assert flat == ("aVR",)

    def test_a_lead_pinned_to_its_extreme_is_saturated(self) -> None:
        window = _signal().T.copy()
        share = int(SATURATION_SHARE * LENGTH) + 10
        window[0, :share] = window[0].max() + 1.0
        _, saturated = self._row(window)
        assert "I" in saturated

    def test_an_ordinary_lead_is_neither(self) -> None:
        flat, saturated = self._row(_signal().T)
        assert flat == () and saturated == ()

    def test_a_flat_lead_is_not_also_reported_as_saturated(self) -> None:
        window = _signal().T.copy()
        window[1, :] = 0.0
        flat, saturated = self._row(window)
        assert flat == ("II",)
        assert "II" not in saturated


class TestConstantsAreNotAccidents:
    def test_the_quantum_is_coarser_than_the_coarsest_gain_on_the_box(self) -> None:
        """INCART's coarsest gain is 240 ADC units per millivolt: a 4.17 uV step."""
        assert MICROVOLTS_PER_STEP > 1000.0 / 240
        assert MICROVOLTS_PER_STEP == 10.0
