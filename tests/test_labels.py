"""Reading the published code tables, and carrying a statement across a link."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ecgchain.database import propagate_labels
from ecgchain.labels import (
    MAPPINGS,
    PARTITION_TO_SOURCE,
    bundle_record_id,
    label_map_table,
    patient_table,
    published_counts,
    scored_table,
    verified_mappings,
)


class TestBundleNaming:
    @pytest.mark.parametrize(("ecg_id", "native"), [(1, "HR00001"), (21799, "HR21799")])
    def test_the_bundle_pads_the_ecg_id_to_five_digits(self, ecg_id: int, native: str) -> None:
        assert bundle_record_id(ecg_id) == native


class TestVerifiedMappings:
    def test_a_missing_file_says_where_it_should_come_from(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="NOTICE.md"):
            verified_mappings(tmp_path)

    def test_a_file_that_changed_is_refused(self, tmp_path: Path) -> None:
        """The digest is the point: a table that moved under us is not read."""
        for name in MAPPINGS:
            (tmp_path / name).write_text("not what was retrieved\n")
        with pytest.raises(ValueError, match="not the"):
            verified_mappings(tmp_path)


class TestPartitions:
    def test_every_challenge_partition_is_named(self) -> None:
        assert len(PARTITION_TO_SOURCE) == 8
        assert all(sid.startswith("challenge-2021/") for sid in PARTITION_TO_SOURCE.values())


class TestPatients:
    def test_a_distribution_that_publishes_no_key_gets_an_empty_table(self, tmp_path: Path) -> None:
        """Silence is reported, not replaced by one record per patient."""
        frame = patient_table("challenge-2021/georgia", tmp_path)
        assert frame.empty
        assert list(frame.columns) == [
            "patient_id",
            "source_id",
            "native_patient_id",
            "record_id",
            "age",
            "sex",
        ]

    def test_ptb_files_each_recording_under_a_patient(self, tmp_path: Path) -> None:
        records = tmp_path / "patient001"
        records.mkdir()
        (records / "s0010_re.hea").write_text("")
        frame = patient_table("physionet/ptbdb", tmp_path)
        assert frame.loc[0, "native_patient_id"] == "patient001"
        assert frame.loc[0, "record_id"] == "physionet/ptbdb:s0010_re"


class TestPropagation:
    @staticmethod
    def _fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        label = pd.DataFrame(
            [
                {"record_id": "b:1", "vocabulary": "SNOMED CT", "code": "426783006"},
                {"record_id": "b:1", "vocabulary": "SNOMED CT", "code": "164889003"},
            ]
        )
        links = pd.DataFrame([{"record_a": "a:1", "record_b": "b:1"}])
        record = pd.DataFrame(
            [{"record_id": "a:1", "source_id": "a"}, {"record_id": "b:1", "source_id": "b"}]
        )
        return label, links, record

    def test_a_statement_travels_to_the_record_that_had_none(self) -> None:
        frame = propagate_labels(*self._fixture())
        assert set(frame["record_id"]) == {"a:1"}
        assert sorted(frame["code"]) == ["164889003", "426783006"]

    def test_the_row_says_it_travelled_and_names_where_from(self) -> None:
        """A reader drops every propagated label with one predicate."""
        frame = propagate_labels(*self._fixture())
        assert set(frame["asserted_by"]) == {"linked record"}
        assert set(frame["via_record_id"]) == {"b:1"}

    def test_a_record_that_carries_its_own_statement_is_left_alone(self) -> None:
        label, links, record = self._fixture()
        label = pd.concat(
            [label, pd.DataFrame([{"record_id": "a:1", "vocabulary": "x", "code": "y"}])],
            ignore_index=True,
        )
        assert propagate_labels(label, links, record).empty

    def test_a_link_between_two_silent_records_carries_nothing(self) -> None:
        label, links, record = self._fixture()
        assert propagate_labels(label.iloc[0:0], links, record).empty

    def test_only_one_origin_is_used_when_several_are_linked(self) -> None:
        label, links, record = self._fixture()
        links = pd.DataFrame(
            [{"record_a": "a:1", "record_b": "b:1"}, {"record_a": "a:1", "record_b": "b:2"}]
        )
        label = pd.concat(
            [label, pd.DataFrame([{"record_id": "b:2", "vocabulary": "s", "code": "z"}])],
            ignore_index=True,
        )
        frame = propagate_labels(label, links, record)
        assert set(frame["via_record_id"]) == {"b:1"}


@pytest.mark.data
class TestAgainstThePublishedTables:
    def test_the_scored_table_holds_thirty_classes(self) -> None:
        try:
            frame = scored_table()
        except FileNotFoundError:
            pytest.skip("the mapping directory is not on this machine")
        assert len(frame) == 30

    def test_a_published_cell_per_class_and_partition(self) -> None:
        try:
            counts = published_counts()
        except FileNotFoundError:
            pytest.skip("the mapping directory is not on this machine")
        assert len(counts) == 30 * 8

    def test_every_mapping_row_carries_its_file_and_digest(self) -> None:
        try:
            frame = label_map_table()
        except FileNotFoundError:
            pytest.skip("the mapping directory is not on this machine")
        assert frame["map_sha256"].notna().all()
        assert frame["map_licence"].notna().all()
        assert set(frame["map_source"]) == set(MAPPINGS)

    def test_the_scp_table_is_not_passed_off_as_snomed(self) -> None:
        """PTB-XL+'s id columns are OMOP concept ids, and the rows say so."""
        try:
            frame = label_map_table()
        except FileNotFoundError:
            pytest.skip("the mapping directory is not on this machine")
        scp = frame[frame["from_vocabulary"] == "SCP-ECG"]
        assert set(scp["to_vocabulary"]) == {"OMOP concept"}
