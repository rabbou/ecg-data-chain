"""Reading a publisher's manifest, and checking the disk against it."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecgchain.manifest import parse_manifest, sha256_file, verify
from ecgchain.sources import source

# The NIST test vectors for SHA-256: the digests of b"abc" and of the empty
# input.  They are the one place in this file where a value comes from outside.
ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class TestDigest:
    def test_known_vectors(self, tmp_path: Path) -> None:
        (tmp_path / "abc").write_bytes(b"abc")
        (tmp_path / "empty").write_bytes(b"")
        assert sha256_file(tmp_path / "abc") == ABC
        assert sha256_file(tmp_path / "empty") == EMPTY

    def test_chunking_does_not_change_the_digest(self, tmp_path: Path) -> None:
        big = tmp_path / "big"
        big.write_bytes(b"abc" * 10_000)
        assert sha256_file(big, chunk_bytes=7) == sha256_file(big, chunk_bytes=1 << 20)


class TestParsing:
    def test_digest_and_path(self, tmp_path: Path) -> None:
        manifest = tmp_path / "SHA256SUMS.txt"
        manifest.write_text(f"{ABC} a/one.dat\n{EMPTY} a/two.dat\n")
        assert parse_manifest(manifest) == {"a/one.dat": ABC, "a/two.dat": EMPTY}

    def test_binary_star_is_not_part_of_the_name(self, tmp_path: Path) -> None:
        manifest = tmp_path / "SHA256SUMS.txt"
        manifest.write_text(f"{ABC} *one.dat\n")
        assert parse_manifest(manifest) == {"one.dat": ABC}

    def test_prefix_selects_and_strips(self, tmp_path: Path) -> None:
        manifest = tmp_path / "SHA256SUMS.txt"
        manifest.write_text(f"{ABC} training/a/one.dat\n{EMPTY} training/b/two.dat\n")
        assert parse_manifest(manifest, "training/a/") == {"one.dat": ABC}

    def test_a_line_that_is_not_a_checksum_is_an_error(self, tmp_path: Path) -> None:
        manifest = tmp_path / "SHA256SUMS.txt"
        manifest.write_text(f"{ABC} one.dat\n# a comment\n")
        with pytest.raises(ValueError, match="not a checksum line"):
            parse_manifest(manifest)

    def test_a_truncated_digest_is_an_error(self, tmp_path: Path) -> None:
        manifest = tmp_path / "SHA256SUMS.txt"
        manifest.write_text("ba7816bf one.dat\n")
        with pytest.raises(ValueError, match="not a checksum line"):
            parse_manifest(manifest)


class TestVerify:
    """The four outcomes stay apart."""

    @staticmethod
    def _tree(tmp_path: Path) -> dict[str, str]:
        (tmp_path / "good").write_bytes(b"abc")
        (tmp_path / "corrupt").write_bytes(b"abd")
        (tmp_path / "unlisted").write_bytes(b"")
        return {"good": ABC, "corrupt": ABC, "absent": EMPTY}

    def test_each_file_lands_in_one_bucket(self, tmp_path: Path) -> None:
        report = verify("t", self._tree(tmp_path), tmp_path)
        assert report.matched == 1
        assert report.mismatched == ["corrupt"]
        assert report.missing_on_disk == ["absent"]
        assert report.unlisted == ["unlisted"]
        assert report.n_declared == 3
        assert report.n_checked == 2
        assert not report.holds

    def test_a_clean_tree_holds(self, tmp_path: Path) -> None:
        (tmp_path / "good").write_bytes(b"abc")
        report = verify("t", {"good": ABC}, tmp_path)
        assert report.holds
        assert report.matched == 1

    def test_a_subset_does_not_report_the_files_it_did_not_look_at(self, tmp_path: Path) -> None:
        """Checking part of 19 GB must not claim the rest is missing."""
        self._tree(tmp_path)
        report = verify("t", {"good": ABC, "absent": EMPTY}, tmp_path, [tmp_path / "good"])
        assert report.matched == 1
        assert report.missing_on_disk == []
        assert report.n_declared == 2
        assert report.n_checked == 1

    def test_a_changed_byte_is_caught(self, tmp_path: Path) -> None:
        """The test that has to fail if the digest is ever taken on trust."""
        path = tmp_path / "good"
        path.write_bytes(b"abc")
        assert verify("t", {"good": ABC}, tmp_path).holds
        path.write_bytes(b"abd")
        assert not verify("t", {"good": ABC}, tmp_path).holds


@pytest.mark.data
class TestAgainstThePublishedManifest:
    def test_a_ptbxl_header_matches_what_physionet_declared(self) -> None:
        entry = source("challenge-2021/ptb-xl")
        if not entry.manifest.exists():
            pytest.skip(f"{entry.manifest} is not on this machine")
        manifest = parse_manifest(entry.manifest, entry.manifest_prefix)
        report = verify(
            entry.source_id, manifest, entry.directory, [entry.directory / "g1/HR00001.hea"]
        )
        assert report.matched == 1
        assert report.holds
