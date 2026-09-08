"""Reading what each record says about itself, without reading its signal.

Two grains come out of a WFDB header: the record -- one tracing as the corpus
ships it -- and the lead, one row per channel of that record.  Both are read
from the header alone.  Nothing here loads a sample, and nothing here writes a
transformed copy of anything: a hospital that asks where a number came from has
to land on the file its own machine wrote, and every intermediate file between
here and there is one more thing to disbelieve.

What the header declares is kept as the header wrote it.  Three of the eight
Challenge sources spell their units ``mv`` and five spell them ``mV``; a chain
that silently normalises the string loses the only evidence that the corpora
disagree.  So ``units_declared`` is verbatim and the comparison that decides
whether a record is in millivolts is the one that ignores case.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import wfdb

from .sources import Source

__all__ = [
    "CANONICAL_LEADS",
    "LeadRow",
    "RecordRow",
    "canonical_lead",
    "in_millivolts",
    "read_header",
    "scan",
]

CANONICAL_LEADS = ("I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6")
_BY_UPPER = {name.upper(): name for name in CANONICAL_LEADS}

MILLIVOLT = "mv"  # compared against, in lower case; never written back


def canonical_lead(name: str) -> str | None:
    """The canonical spelling of a lead name, or None when it is not one of the twelve.

    PTB's Frank leads (vx, vy, vz) are the reason this returns None rather than
    raising: a fifteen-lead record is a fact about the corpus, not an error.
    """
    return _BY_UPPER.get(name.strip().upper())


def in_millivolts(units: str) -> bool:
    """Whether a declared unit string means millivolts, whatever its case."""
    return units.strip().lower() == MILLIVOLT


@dataclass(frozen=True)
class RecordRow:
    """One tracing as its corpus ships it."""

    record_id: str  # "<source_id>:<native_record_id>", unique across distributions
    source_id: str
    native_record_id: str
    header_path: str  # relative to the source's directory
    signal_paths: tuple[str, ...]
    n_leads: int
    sampling_rate_hz: float
    n_samples: int
    units_declared: tuple[str, ...]  # the distinct spellings, as written
    all_millivolts: bool
    age: str | None
    sex: str | None
    dx: tuple[str, ...]  # SNOMED CT codes, when the header carries them

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.sampling_rate_hz


@dataclass(frozen=True)
class LeadRow:
    """One channel of one tracing."""

    record_id: str
    position: int
    name_native: str
    name_canonical: str | None
    units_declared: str
    gain: float
    baseline: int
    adc_zero: int


def _comment_value(comments: list[str], key: str) -> str | None:
    prefix = f"{key}:"
    for comment in comments:
        text = comment.strip()
        if text.lower().startswith(prefix.lower()):
            value = text[len(prefix) :].strip()
            return value or None
    return None


def read_header(source: Source, header: Path) -> tuple[RecordRow, tuple[LeadRow, ...]]:
    """The record and lead rows for one ``.hea`` file."""
    meta: Any = wfdb.rdheader(str(header.with_suffix("")))
    native = header.stem
    record_id = f"{source.source_id}:{native}"
    comments = list(meta.comments or [])
    units = [str(unit) for unit in (meta.units or [])]
    dx = _comment_value(comments, "Dx")

    leads = tuple(
        LeadRow(
            record_id=record_id,
            position=position,
            name_native=str(name),
            name_canonical=canonical_lead(str(name)),
            units_declared=units[position] if position < len(units) else "",
            gain=float(meta.adc_gain[position]),
            baseline=int(meta.baseline[position]),
            adc_zero=int(meta.adc_zero[position]),
        )
        for position, name in enumerate(meta.sig_name or [])
    )
    row = RecordRow(
        record_id=record_id,
        source_id=source.source_id,
        native_record_id=native,
        header_path=header.relative_to(source.directory).as_posix(),
        signal_paths=tuple(sorted({str(name) for name in (meta.file_name or [])})),
        n_leads=int(meta.n_sig),
        sampling_rate_hz=float(meta.fs),
        n_samples=int(meta.sig_len),
        units_declared=tuple(sorted(set(units))),
        all_millivolts=bool(units) and all(in_millivolts(unit) for unit in units),
        age=_comment_value(comments, "Age"),
        sex=_comment_value(comments, "Sex"),
        dx=tuple(code.strip() for code in dx.split(",")) if dx else (),
    )
    return row, leads


def headers(source: Source) -> Iterator[Path]:
    """Every ``.hea`` file of a source, in a stable order."""
    yield from sorted(source.directory.rglob("*.hea"))


def scan(source: Source) -> tuple[list[RecordRow], list[LeadRow]]:
    """Read every header of a source.

    Reading 88,253 headers is a heavy pass; drive it from
    ``scripts/scan_records.py`` under a capped scope rather than from a test.
    """
    records: list[RecordRow] = []
    leads: list[LeadRow] = []
    for header in headers(source):
        row, lead_rows = read_header(source, header)
        records.append(row)
        leads.extend(lead_rows)
    return records, leads
