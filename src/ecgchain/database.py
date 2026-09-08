"""The deliverable: Parquet files a client queries with an embedded engine.

One table per grain, and the grain is a sentence: one row per what.  The names
follow the waveform registry the OHDSI working group proposes -- an occurrence,
a registry of files, channel metadata, derived features -- without installing
the common data model, so a client who already runs OMOP has a short migration
and a client who does not has no server to operate.

The join that matters is one hop.  A tracing carries the id of the file it came
from, and that file carries the digest its publisher released, so

    SELECT r.record_id, f.relative_path, f.sha256_declared
    FROM record r JOIN source_file f USING (file_id)

answers "where did this come from" for any record in the delivery.  Everything
else in the schema is arranged so that this stays one join: it is the question
a hospital data lead asks first, and an index that has to be kept in step with
the files would be a second thing to trust.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .duplicates import DuplicateLink, groups
from .ingest import LeadRow, RecordRow
from .quality import QualityRow
from .sources import Source

__all__ = [
    "TABLES",
    "duplicate_link_table",
    "Delivery",
    "connect",
    "label_table",
    "lead_table",
    "quality_table",
    "record_table",
    "signal_group_table",
    "source_file_table",
    "source_table",
    "trace",
    "write",
]

TABLES = (
    "source",
    "source_file",
    "record",
    "lead",
    "label",
    "quality",
    "signal_group",
    "duplicate_link",
)


def file_id(source_id: str, relative_path: str) -> str:
    """A file's key: its distribution and its path inside it."""
    return f"{source_id}:{relative_path}"


def source_table(entries: Iterable[Source]) -> pd.DataFrame:
    """One row per corpus distribution."""
    return pd.DataFrame(
        [
            {
                "source_id": entry.source_id,
                "corpus": entry.corpus,
                "distribution": entry.distribution,
                "version": entry.version,
                "publisher": entry.publisher,
                "licence": entry.licence,
                "url": entry.url,
                "directory": str(entry.directory),
                "manifest": str(entry.manifest),
            }
            for entry in entries
        ]
    )


def source_file_table(
    source_id: str, rows: Iterable[RecordRow], declared: dict[str, str]
) -> pd.DataFrame:
    """One row per file as its publisher shipped it.

    ``declared`` is the publisher's manifest, keyed by path relative to the
    distribution.  A file the manifest does not list keeps a null digest rather
    than one of ours: the point of the column is what the publisher said.
    """
    seen: dict[str, dict[str, object]] = {}
    for row in rows:
        folder = Path(row.header_path).parent
        for relative_path, role in [(row.header_path, "header")] + [
            ((folder / name).as_posix(), "signal") for name in row.signal_paths
        ]:
            key = file_id(source_id, relative_path)
            seen.setdefault(
                key,
                {
                    "file_id": key,
                    "source_id": source_id,
                    "relative_path": relative_path,
                    "role": role,
                    "sha256_declared": declared.get(relative_path),
                },
            )
    return pd.DataFrame(list(seen.values()))


def record_table(rows: Iterable[RecordRow]) -> pd.DataFrame:
    """One row per tracing as its corpus ships it."""
    return pd.DataFrame(
        [
            {
                "record_id": row.record_id,
                "source_id": row.source_id,
                "native_record_id": row.native_record_id,
                "header_file_id": file_id(row.source_id, row.header_path),
                "signal_file_id": file_id(
                    row.source_id,
                    (Path(row.header_path).parent / row.signal_paths[0]).as_posix(),
                )
                if row.signal_paths
                else None,
                "n_leads": row.n_leads,
                "sampling_rate_hz": row.sampling_rate_hz,
                "n_samples": row.n_samples,
                "duration_s": row.duration_s,
                "units_declared": "|".join(row.units_declared),
                "units_are_declared": row.units_are_declared,
                "age": row.age,
                "sex": row.sex,
            }
            for row in rows
        ]
    )


def lead_table(rows: Iterable[LeadRow]) -> pd.DataFrame:
    """One row per channel of a tracing."""
    return pd.DataFrame(
        [
            {
                "record_id": row.record_id,
                "position": row.position,
                "name_native": row.name_native,
                "name_canonical": row.name_canonical,
                "units_declared": row.units_declared,
                "gain": row.gain,
                "baseline": row.baseline,
                "adc_zero": row.adc_zero,
            }
            for row in rows
        ]
    )


def label_table(rows: Iterable[RecordRow]) -> pd.DataFrame:
    """One row per statement about a tracing, in the vocabulary it was written in."""
    return pd.DataFrame(
        [
            {
                "record_id": row.record_id,
                "vocabulary": "SNOMED CT",
                "code": code,
                "source_field": "header comment Dx",
                "asserted_by": "corpus",
            }
            for row in rows
            for code in row.dx
        ],
        columns=["record_id", "vocabulary", "code", "source_field", "asserted_by"],
    )


def quality_table(rows: Iterable[QualityRow]) -> pd.DataFrame:
    """One row per tracing judged."""
    return pd.DataFrame(
        [
            {
                "record_id": row.record_id,
                "missing_leads": "|".join(row.missing_leads),
                "flat_leads": "|".join(row.flat_leads),
                "saturated_leads": "|".join(row.saturated_leads),
                "n_nonfinite": row.n_nonfinite,
                "n_samples_read": row.n_samples_read,
                "signal_digest": row.signal_digest,
                "holds": row.holds,
            }
            for row in rows
        ]
    )


def signal_group_table(digests: dict[str, str | None]) -> pd.DataFrame:
    """One row per tracing, carrying the group of records that hold it.

    This is the column a split is drawn on.  Splitting by patient does not
    separate a recording from its own copy under another record id, and the
    copies are here: CPSC-2018 ships 6,877 records holding 6,622 tracings.
    """
    found = groups(digests)
    rows = [
        {
            "record_id": record_id,
            "signal_group_id": digest,
            "group_size": len(members),
        }
        for digest, members in found.items()
        for record_id in members
    ]
    return pd.DataFrame(rows, columns=["record_id", "signal_group_id", "group_size"])


def duplicate_link_table(links: Iterable[DuplicateLink]) -> pd.DataFrame:
    """One row per pair of records the screen linked, with its scope and sieve."""
    return pd.DataFrame(
        [
            {
                "record_a": link.record_a,
                "record_b": link.record_b,
                "sieve": link.sieve,
                "score": link.score,
                "scope": link.scope,
            }
            for link in links
        ],
        columns=["record_a", "record_b", "sieve", "score", "scope"],
    )


@dataclass(frozen=True)
class Delivery:
    """Where the Parquet files live."""

    directory: Path

    def path(self, table: str) -> Path:
        return self.directory / f"{table}.parquet"

    @property
    def present(self) -> tuple[str, ...]:
        return tuple(table for table in TABLES if self.path(table).exists())


def write(tables: dict[str, pd.DataFrame], directory: Path) -> Delivery:
    """Write each table to its own Parquet file."""
    directory.mkdir(parents=True, exist_ok=True)
    delivery = Delivery(directory)
    for name, frame in tables.items():
        frame.to_parquet(delivery.path(name), index=False)
    return delivery


def connect(delivery: Delivery) -> Any:
    """A DuckDB connection with one view per table, read straight from Parquet."""
    import duckdb

    connection = duckdb.connect()
    for table in delivery.present:
        connection.execute(
            f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{delivery.path(table)}')"
        )
    return connection


TRACE_QUERY = """
SELECT r.record_id, r.source_id, f.relative_path, f.sha256_declared
FROM record r JOIN source_file f ON f.file_id = r.signal_file_id
WHERE r.record_id = ?
"""


def trace(connection: Any, record_id: str) -> dict[str, object] | None:
    """Where one tracing came from, in a single join."""
    row = connection.execute(TRACE_QUERY, [record_id]).fetchone()
    if row is None:
        return None
    return dict(
        zip(["record_id", "source_id", "relative_path", "sha256_declared"], row, strict=True)
    )
