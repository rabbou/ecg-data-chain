"""The catalogue, and the two corpora that prove it has to key on packaging."""

from __future__ import annotations

import pytest

from ecgchain.sources import Source, source, sources


class TestCatalogue:
    def test_eleven_distributions(self) -> None:
        assert len(sources()) == 11

    def test_ids_are_unique(self) -> None:
        ids = [entry.source_id for entry in sources()]
        assert len(set(ids)) == len(ids)

    def test_lookup_by_id(self) -> None:
        assert source("challenge-2021/ptb-xl").corpus == "ptb-xl"

    def test_unknown_id_names_what_there_is(self) -> None:
        with pytest.raises(KeyError, match="challenge-2021/ptb-xl"):
            source("ptbxl")


class TestTheCorporaThatArriveTwice:
    """INCART and PTB are each on the box under two distributions.

    Their record counts differ -- INCART is 75 records as PhysioNet publishes
    it and 74 inside the Challenge bundle -- so a catalogue keyed on the corpus
    name would silently merge two things that are not the same set of files.
    """

    def test_exactly_two_corpora_appear_twice(self) -> None:
        seen: dict[str, list[str]] = {}
        for entry in sources():
            seen.setdefault(entry.corpus, []).append(entry.source_id)
        twice = {corpus for corpus, ids in seen.items() if len(ids) > 1}
        assert twice == {"incart", "ptb"}

    @pytest.mark.parametrize(
        ("first", "second"),
        [
            ("challenge-2021/st_petersburg_incart", "physionet/incartdb"),
            ("challenge-2021/ptb", "physionet/ptbdb"),
        ],
    )
    def test_the_two_packagings_are_different_directories(self, first: str, second: str) -> None:
        a, b = source(first), source(second)
        assert a.corpus == b.corpus
        assert a.directory != b.directory
        assert a.manifest != b.manifest


class TestWhatEachEntryCarries:
    def test_licence_is_absent_rather_than_guessed(self) -> None:
        """A distribution that ships no licence file says so."""
        assert source("challenge-2021/ptb-xl").licence == "CC BY 4.0"
        assert source("physionet/ludb").licence == "ODC-By 1.0"
        assert source("physionet/incartdb").licence is None
        assert source("physionet/ptbdb").licence is None

    def test_url_is_built_from_slug_and_version(self) -> None:
        assert source("physionet/ludb").url == "https://physionet.org/content/ludb/1.0.1/"

    def test_challenge_partitions_share_one_manifest(self) -> None:
        challenge = [e for e in sources() if e.distribution == "challenge-2021"]
        assert len({e.manifest for e in challenge}) == 1
        assert len({e.manifest_prefix for e in challenge}) == len(challenge)

    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            source("physionet/ludb").version = "9.9.9"  # type: ignore[misc]

    def test_directory_of_a_whole_distribution_is_its_root(self) -> None:
        entry: Source = source("physionet/ludb")
        assert entry.directory == entry.root


@pytest.mark.data
class TestOnDisk:
    """The counts the publishers' own manifests carry, read 2026-09-08."""

    @pytest.mark.parametrize(
        ("source_id", "n_entries"),
        [
            ("challenge-2021/chapman_shaoxing", 20505),
            ("challenge-2021/cpsc_2018", 13762),
            ("challenge-2021/cpsc_2018_extra", 6910),
            ("challenge-2021/georgia", 20699),
            ("challenge-2021/ningbo", 69845),
            ("challenge-2021/ptb", 1033),
            ("challenge-2021/ptb-xl", 43696),
            ("challenge-2021/st_petersburg_incart", 149),
            ("physionet/incartdb", 230),
            ("physionet/ludb", 2805),
            ("physionet/ptbdb", 1651),
        ],
    )
    def test_manifest_entry_counts(self, source_id: str, n_entries: int) -> None:
        from ecgchain.manifest import parse_manifest

        entry = source(source_id)
        if not entry.manifest.exists():
            pytest.skip(f"{entry.manifest} is not on this machine")
        assert len(parse_manifest(entry.manifest, entry.manifest_prefix)) == n_entries

    def test_every_directory_is_there(self) -> None:
        missing = [e.source_id for e in sources() if not e.directory.is_dir()]
        assert missing == []
