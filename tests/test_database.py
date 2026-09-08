"""The tables, and the one join that answers where a tracing came from."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ecgchain.database import (
    TABLES,
    Delivery,
    connect,
    duplicate_link_table,
    label_table,
    lead_table,
    quality_table,
    record_table,
    signal_group_table,
    source_file_table,
    source_table,
    trace,
    write,
)
from ecgchain.duplicates import ACROSS, WITHIN, DuplicateLink
from ecgchain.ingest import LeadRow, RecordRow
from ecgchain.quality import QualityRow
from ecgchain.sources import source

DIGEST = "d" * 64


def _record(
    native: str = "R1", source_id: str = "test/tiny", dx: tuple[str, ...] = ()
) -> RecordRow:
    return RecordRow(
        record_id=f"{source_id}:{native}",
        source_id=source_id,
        native_record_id=native,
        header_path=f"g1/{native}.hea",
        signal_paths=(f"{native}.mat",),
        n_leads=12,
        sampling_rate_hz=500.0,
        n_samples=5000,
        units_declared=("mV",),
        units_are_declared=True,
        all_millivolts=True,
        age="35",
        sex="Male",
        dx=dx,
    )


class TestTables:
    def test_a_source_row_carries_its_licence_and_url(self) -> None:
        frame = source_table([source("physionet/ludb")])
        assert frame.loc[0, "licence"] == "ODC-By 1.0"
        assert str(frame.loc[0, "url"]).endswith("/ludb/1.0.1/")

    def test_a_file_keeps_the_publisher_digest_and_nothing_else(self) -> None:
        frame = source_file_table("test/tiny", [_record()], {"g1/R1.mat": DIGEST})
        signal = frame[frame["role"] == "signal"].iloc[0]
        assert signal["sha256_declared"] == DIGEST
        header = frame[frame["role"] == "header"].iloc[0]
        assert pd.isna(header["sha256_declared"])

    def test_a_file_the_manifest_does_not_list_has_no_digest(self) -> None:
        """Never one of ours: the column is what the publisher said."""
        frame = source_file_table("test/tiny", [_record()], {})
        assert frame["sha256_declared"].isna().all()

    def test_a_record_points_at_its_signal_file(self) -> None:
        frame = record_table([_record()])
        assert frame.loc[0, "signal_file_id"] == "test/tiny:g1/R1.mat"
        assert frame.loc[0, "header_file_id"] == "test/tiny:g1/R1.hea"

    def test_labels_come_out_one_row_per_statement(self) -> None:
        frame = label_table([_record(dx=("427084000", "164865005"))])
        assert list(frame["code"]) == ["427084000", "164865005"]
        assert set(frame["vocabulary"]) == {"SNOMED CT"}

    def test_a_record_with_no_statement_makes_no_label_row(self) -> None:
        assert label_table([_record()]).empty

    def test_a_lead_row_per_channel(self) -> None:
        leads = [
            LeadRow("test/tiny:R1", position, "I", "I", "mV", 1000.0, 0, 0)
            for position in range(12)
        ]
        assert len(lead_table(leads)) == 12

    def test_quality_carries_the_verdict_and_the_fingerprint(self) -> None:
        row = QualityRow("test/tiny:R1", (), ("aVR",), (), 0, 5000, DIGEST)
        frame = quality_table([row])
        assert frame.loc[0, "flat_leads"] == "aVR"
        assert not frame.loc[0, "holds"]
        assert frame.loc[0, "signal_digest"] == DIGEST


class TestSignalGroups:
    @staticmethod
    def _links(*pairs: tuple[str, str]) -> pd.DataFrame:
        return pd.DataFrame(
            [{"record_a": a, "record_b": b} for a, b in pairs],
            columns=["record_a", "record_b"],
        )

    def test_records_holding_one_tracing_share_a_group(self) -> None:
        frame = signal_group_table({"a:1": "x", "a:2": "x", "b:1": "y"})
        by_record = dict(zip(frame["record_id"], frame["signal_group_id"], strict=True))
        assert by_record["a:1"] == by_record["a:2"]
        assert by_record["b:1"] != by_record["a:1"]

    def test_the_group_size_is_carried_on_every_member(self) -> None:
        frame = signal_group_table({"a:1": "x", "a:2": "x", "b:1": "y"})
        sizes = dict(zip(frame["record_id"], frame["group_size"], strict=True))
        assert sizes == {"a:1": 2, "a:2": 2, "b:1": 1}

    def test_a_record_with_no_fingerprint_is_in_no_group(self) -> None:
        assert signal_group_table({"a:1": None}).empty

    def test_a_link_the_fingerprint_missed_still_joins_the_group(self) -> None:
        """The defect this closes: all 516 PTB pairs are correlation links.

        A group built from fingerprints alone puts a record and its own copy in
        different groups, so a split drawn on the column separates them.
        """
        digests = {"a:1": "x", "b:1": "y"}
        alone = signal_group_table(digests)
        assert alone.loc[0, "signal_group_id"] != alone.loc[1, "signal_group_id"]
        joined = signal_group_table(digests, self._links(("a:1", "b:1")))
        assert joined.loc[0, "signal_group_id"] == joined.loc[1, "signal_group_id"]
        assert set(joined["group_size"]) == {2}

    def test_the_group_closes_over_a_chain_of_links(self) -> None:
        digests = {"a:1": "x", "b:1": "y", "c:1": "z"}
        frame = signal_group_table(digests, self._links(("a:1", "b:1"), ("b:1", "c:1")))
        assert frame["signal_group_id"].nunique() == 1
        assert set(frame["group_size"]) == {3}

    def test_the_fingerprint_stays_readable_on_its_own(self) -> None:
        frame = signal_group_table({"a:1": "x", "b:1": "y"}, self._links(("a:1", "b:1")))
        assert sorted(frame["fingerprint"]) == ["x", "y"]

    def test_the_group_is_named_by_the_smallest_record_it_holds(self) -> None:
        frame = signal_group_table({"b:1": "x", "a:1": "y"}, self._links(("b:1", "a:1")))
        assert set(frame["signal_group_id"]) == {"a:1"}

    def test_a_link_to_a_record_outside_the_digests_is_ignored(self) -> None:
        frame = signal_group_table({"a:1": "x"}, self._links(("a:1", "z:9")))
        assert len(frame) == 1
        assert frame.loc[0, "group_size"] == 1


class TestDuplicateLinkTable:
    def test_both_scopes_are_kept_apart(self) -> None:
        frame = duplicate_link_table(
            [
                DuplicateLink.between("a:1", "a:2", "signal", 1.0, WITHIN),
                DuplicateLink.between("a:1", "b:1", "correlation", 0.997, ACROSS),
            ]
        )
        assert sorted(frame["scope"]) == sorted([ACROSS, WITHIN])
        assert set(frame["sieve"]) == {"signal", "correlation"}


class TestTheOneJoin:
    @staticmethod
    def _delivery(tmp_path: Path) -> Delivery:
        rows = [_record("R1"), _record("R2")]
        return write(
            {
                "source": source_table([source("physionet/ludb")]),
                "source_file": source_file_table(
                    "test/tiny", rows, {"g1/R1.mat": DIGEST, "g1/R2.mat": "e" * 64}
                ),
                "record": record_table(rows),
            },
            tmp_path / "delivery",
        )

    def test_a_tracing_reaches_its_file_and_the_publisher_digest(self, tmp_path: Path) -> None:
        connection = connect(self._delivery(tmp_path))
        found = trace(connection, "test/tiny:R1")
        assert found == {
            "record_id": "test/tiny:R1",
            "source_id": "test/tiny",
            "relative_path": "g1/R1.mat",
            "sha256_declared": DIGEST,
        }

    def test_the_query_holds_exactly_one_join(self) -> None:
        """The criterion is one hop, not an index kept in step with the files."""
        from ecgchain.database import TRACE_QUERY

        assert TRACE_QUERY.upper().count(" JOIN ") == 1

    def test_an_unknown_record_traces_to_nothing(self, tmp_path: Path) -> None:
        connection = connect(self._delivery(tmp_path))
        assert trace(connection, "test/tiny:R9") is None

    def test_only_the_written_tables_become_views(self, tmp_path: Path) -> None:
        delivery = self._delivery(tmp_path)
        assert delivery.present == ("source", "source_file", "record")
        assert set(TABLES) > set(delivery.present)


@pytest.mark.data
class TestTheBuiltDelivery:
    """The delivery on this box, if it has been built."""

    @staticmethod
    def _delivery() -> Delivery:
        delivery = Delivery(Path(__file__).resolve().parents[1] / "results" / "delivery")
        if not delivery.present:
            pytest.skip("run scripts/build_database.py")
        return delivery

    def test_a_tracing_taken_at_random_reaches_its_source_file(self) -> None:
        delivery = self._delivery()
        connection = connect(delivery)
        record_id = connection.execute(
            "SELECT record_id FROM record USING SAMPLE 1 ROWS (reservoir, 20260908)"
        ).fetchone()[0]
        found = trace(connection, record_id)
        assert found is not None
        assert found["relative_path"]
        assert found["sha256_declared"]
