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

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .duplicates import DuplicateLink, groups
from .ingest import LeadRow, RecordRow
from .quality import QualityRow
from .sources import Source

__all__ = [
    "DEFERRED",
    "TABLES",
    "duplicate_link_table",
    "propagate_labels",
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
    "label_propagated",
    "label_map",
    "patient",
    "quality",
    "signal_group",
    "duplicate_link",
)

# Two tables of the schema stay empty until something reads them.  `split` waits
# for its first consumer, and `signal_window` for a delivery that serves arrays
# rather than pointing at the files; filling either now would be filling it for
# the shape of the schema rather than for a reader.
DEFERRED = ("split", "signal_window")


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


def signal_group_table(
    digests: Mapping[str, str | None], links: pd.DataFrame | None = None
) -> pd.DataFrame:
    """One row per record, carrying the group of records that hold its tracing.

    This is the column a split is drawn on, so it has to close over every sieve
    and not only the fingerprint.  The correlation sieve exists precisely
    because a fingerprint misses pairs: all 516 of PTB's cross-packaging pairs
    are correlation links, and a group built from fingerprints alone would put
    a record and its own copy on opposite sides of a fold.

    The group is therefore the connected component over the fingerprint groups
    and every link together, named by the smallest record id it contains.  The
    fingerprint stays in its own column, so a reader can still ask which
    records are byte-equal to ten microvolts.
    """
    parent: dict[str, str] = {record_id: record_id for record_id in digests}

    def find(node: str) -> str:
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for members in groups(digests).values():
        for other in members[1:]:
            union(members[0], other)
    if links is not None:
        for left, right in zip(links["record_a"], links["record_b"], strict=True):
            if left in parent and right in parent:
                union(str(left), str(right))

    component = {record_id: find(record_id) for record_id in parent}
    sizes = Counter(component.values())
    rows = [
        {
            "record_id": record_id,
            "signal_group_id": root,
            "group_size": sizes[root],
            "fingerprint": digests[record_id],
        }
        for record_id, root in sorted(component.items())
        if digests[record_id] is not None
    ]
    return pd.DataFrame(rows, columns=["record_id", "signal_group_id", "group_size", "fingerprint"])


def propagate_labels(
    label: pd.DataFrame, links: pd.DataFrame, record: pd.DataFrame
) -> pd.DataFrame:
    """Carry a statement across a link, to a record whose corpus asserted none.

    Four of the twelve distributions ship no diagnosis at all, and three of
    those four are packagings of a corpus whose other packaging does.  A
    statement can therefore travel the link the screen established -- which is
    the whole point of having established it -- provided the row says it
    travelled and names what it came from, so that a reader can drop every
    propagated label with one predicate.
    """
    statements: dict[str, list[tuple[str, str]]] = {}
    for record_id, vocabulary, code in zip(
        label["record_id"], label["vocabulary"], label["code"], strict=True
    ):
        statements.setdefault(str(record_id), []).append((str(vocabulary), str(code)))

    source_of = dict(zip(record["record_id"], record["source_id"], strict=True))
    origin_of: dict[str, str] = {}
    for column_a, column_b in (("record_a", "record_b"), ("record_b", "record_a")):
        for target, origin in zip(links[column_a], links[column_b], strict=True):
            if target in statements or origin not in statements:
                continue
            held = origin_of.get(str(target))
            if held is None or str(origin) < held:
                origin_of[str(target)] = str(origin)

    rows = [
        {
            "record_id": target,
            "source_id": source_of.get(target),
            "vocabulary": vocabulary,
            "code": code,
            "source_field": f"propagated from {origin}",
            "asserted_by": "linked record",
            "via_record_id": origin,
        }
        for target, origin in sorted(origin_of.items())
        for vocabulary, code in statements[origin]
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "record_id",
            "source_id",
            "vocabulary",
            "code",
            "source_field",
            "asserted_by",
            "via_record_id",
        ],
    )


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
