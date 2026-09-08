"""What a header declares, kept as the header wrote it."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecgchain.ingest import canonical_lead, in_millivolts, read_header, scan
from ecgchain.sources import Source, source

HEADER = """tiny 2 500 5000
tiny.dat 16 1000.0(0)/{units} 16 0 -115 13047 0 I
tiny.dat 16 1000.0(0)/{units} 16 0 -50 11561 0 {second}
# Age: 35
# Sex: Male
# Dx: 427084000,164865005
"""


def _source(root: Path) -> Source:
    return Source(
        source_id="test/tiny",
        corpus="tiny",
        distribution="test",
        version="0",
        publisher="nobody",
        licence=None,
        slug="tiny",
        root=root,
        subdir="",
        manifest_name="SHA256SUMS.txt",
        manifest_prefix="",
    )


def _write(root: Path, units: str = "mV", second: str = "II") -> Path:
    header = root / "tiny.hea"
    header.write_text(HEADER.format(units=units, second=second))
    return header


class TestLeadNames:
    @pytest.mark.parametrize(("given", "want"), [("I", "I"), ("avr", "aVR"), ("AVL", "aVL")])
    def test_case_does_not_decide_the_lead(self, given: str, want: str) -> None:
        assert canonical_lead(given) == want

    @pytest.mark.parametrize("name", ["vx", "vy", "vz"])
    def test_the_frank_leads_are_not_one_of_the_twelve(self, name: str) -> None:
        """PTB ships fifteen channels. That is a fact about the corpus, not an error."""
        assert canonical_lead(name) is None


class TestUnits:
    @pytest.mark.parametrize("units", ["mv", "mV", "MV", " mV "])
    def test_every_case_form_means_millivolts(self, units: str) -> None:
        assert in_millivolts(units)

    @pytest.mark.parametrize("units", ["uV", "V", "adu", ""])
    def test_anything_else_does_not(self, units: str) -> None:
        assert not in_millivolts(units)


class TestReadingAHeader:
    def test_the_declared_spelling_survives(self, tmp_path: Path) -> None:
        """A chain that normalises the string loses the evidence corpora disagree."""
        row, _ = read_header(_source(tmp_path), _write(tmp_path, units="mv"))
        assert row.units_declared == ("mv",)
        assert row.all_millivolts

    def test_the_record_id_carries_its_distribution(self, tmp_path: Path) -> None:
        row, _ = read_header(_source(tmp_path), _write(tmp_path))
        assert row.record_id == "test/tiny:tiny"
        assert row.native_record_id == "tiny"

    def test_shape_and_duration(self, tmp_path: Path) -> None:
        row, _ = read_header(_source(tmp_path), _write(tmp_path))
        assert (row.n_leads, row.sampling_rate_hz, row.n_samples) == (2, 500.0, 5000)
        assert row.duration_s == 10.0

    def test_the_comment_fields(self, tmp_path: Path) -> None:
        row, _ = read_header(_source(tmp_path), _write(tmp_path))
        assert (row.age, row.sex) == ("35", "Male")
        assert row.dx == ("427084000", "164865005")

    def test_one_lead_row_per_channel(self, tmp_path: Path) -> None:
        _, leads = read_header(_source(tmp_path), _write(tmp_path))
        assert [lead.position for lead in leads] == [0, 1]
        assert [lead.name_native for lead in leads] == ["I", "II"]
        assert leads[0].gain == 1000.0
        assert leads[0].baseline == 0

    def test_a_channel_outside_the_twelve_is_kept_with_no_canonical_name(
        self, tmp_path: Path
    ) -> None:
        _, leads = read_header(_source(tmp_path), _write(tmp_path, second="vx"))
        assert leads[1].name_native == "vx"
        assert leads[1].name_canonical is None

    def test_no_signal_file_is_needed(self, tmp_path: Path) -> None:
        """Reading a header must not touch the .dat beside it."""
        header = _write(tmp_path)
        assert not (tmp_path / "tiny.dat").exists()
        row, _ = read_header(_source(tmp_path), header)
        assert row.signal_paths == ("tiny.dat",)


@pytest.mark.data
class TestTheTwoPackagingsOfIncart:
    """The pair that decides whether the catalogue may key on the corpus name.

    Same corpus, same 12 channels at 257 Hz, 462,600 samples. The Challenge
    bundle holds one record fewer, renames every record, changes the ADC gain
    from 306 to 1000 units per millivolt, and adds a unit string where the
    original had none. Nothing but the distribution key separates them.
    """

    @staticmethod
    def _scan(source_id: str) -> list:
        entry = source(source_id)
        if not entry.directory.is_dir():
            pytest.skip(f"{entry.directory} is not on this machine")
        records, _ = scan(entry)
        return records

    def test_record_counts_differ(self) -> None:
        assert len(self._scan("physionet/incartdb")) == 75
        assert len(self._scan("challenge-2021/st_petersburg_incart")) == 74

    def test_one_packaging_names_its_units_and_the_other_does_not(self) -> None:
        """PhysioNet's headers stop at the gain; the bundle's say mv."""
        physionet = self._scan("physionet/incartdb")
        bundle = self._scan("challenge-2021/st_petersburg_incart")
        assert {u for row in physionet for u in row.units_declared} == set()
        assert not any(row.units_are_declared for row in physionet)
        assert {u for row in bundle for u in row.units_declared} == {"mv"}
        assert all(row.units_are_declared for row in bundle)

    def test_no_record_id_is_shared(self) -> None:
        physionet = {row.native_record_id for row in self._scan("physionet/incartdb")}
        challenge = {
            row.native_record_id for row in self._scan("challenge-2021/st_petersburg_incart")
        }
        assert physionet & challenge == set()

    def test_the_signal_shape_is_the_same(self) -> None:
        for source_id in ("physionet/incartdb", "challenge-2021/st_petersburg_incart"):
            rows = self._scan(source_id)
            assert {(r.n_leads, r.sampling_rate_hz, r.n_samples) for r in rows} == {
                (12, 257.0, 462600)
            }
