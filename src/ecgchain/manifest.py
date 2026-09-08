"""The publisher's checksums come first; ours are only the witness.

Every corpus in the first delivery ships a SHA256SUMS.txt written by whoever
published it.  Hashing the files ourselves and storing the result would prove
that the box agrees with itself.  Checking them against the publisher's file
proves the box holds what the publisher released, which is the claim a hospital
data lead actually wants, and it is the reason the chain starts here rather
than at the signal.

A report keeps the four outcomes apart -- files that match, files that differ,
files the manifest lists and the disk does not have, files on disk the manifest
never mentioned -- because collapsing them into one number would hide the only
two that mean something has gone wrong.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["ManifestReport", "parse_manifest", "sha256_file", "verify"]

_CHUNK_BYTES = 1 << 20  # a megabyte: the files run to hundreds of them


def sha256_file(path: Path, chunk_bytes: int = _CHUNK_BYTES) -> str:
    """The SHA-256 of a file, read in chunks so a 4 GB archive fits in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def parse_manifest(path: Path, prefix: str = "") -> dict[str, str]:
    """Read a SHA256SUMS file into relative path -> digest.

    The format is the one ``sha256sum`` writes: the digest, a separator, the
    path.  ``prefix`` keeps only the entries under one corpus of a multi-corpus
    distribution and strips it, so the keys are relative to that corpus.
    A line that is not a digest and a path is an error, not a line to skip:
    a manifest we cannot read in full is a manifest we cannot rely on.
    """
    entries: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.rstrip("\n")
            if not text:
                continue
            digest, separator, name = text.partition(" ")
            if not separator or len(digest) != 64:
                raise ValueError(f"{path}:{number}: not a checksum line: {text!r}")
            name = name.lstrip(" *")  # sha256sum marks binary reads with a star
            if prefix and not name.startswith(prefix):
                continue
            entries[name[len(prefix) :]] = digest
    return entries


@dataclass
class ManifestReport:
    """What the publisher's manifest and the disk say about each other."""

    source_id: str
    n_declared: int  # entries in the manifest, after the prefix filter
    matched: int = 0
    mismatched: list[str] = field(default_factory=list)
    missing_on_disk: list[str] = field(default_factory=list)
    unlisted: list[str] = field(default_factory=list)

    @property
    def n_checked(self) -> int:
        return self.matched + len(self.mismatched)

    @property
    def holds(self) -> bool:
        """True when every file checked matched and nothing was missing."""
        return not self.mismatched and not self.missing_on_disk


def _relative(paths: Iterable[Path], directory: Path) -> Iterator[tuple[str, Path]]:
    for path in paths:
        yield path.relative_to(directory).as_posix(), path


def verify(
    source_id: str,
    manifest: dict[str, str],
    directory: Path,
    paths: Iterable[Path] | None = None,
) -> ManifestReport:
    """Check files under ``directory`` against ``manifest``.

    ``paths`` restricts the check to a subset -- verifying 53 GB is a job for a
    capped scope, not for a test run -- and the report says how many of the
    declared files were actually read.  With ``paths`` left out, every file
    under the directory is checked and files the manifest never listed are
    reported rather than ignored.
    """
    subset = paths is not None
    candidates = paths if paths is not None else (p for p in directory.rglob("*") if p.is_file())
    report = ManifestReport(source_id=source_id, n_declared=len(manifest))
    seen: set[str] = set()
    for name, path in _relative(candidates, directory):
        declared = manifest.get(name)
        if declared is None:
            report.unlisted.append(name)
            continue
        seen.add(name)
        if sha256_file(path) == declared:
            report.matched += 1
        else:
            report.mismatched.append(name)
    if not subset:
        report.missing_on_disk = sorted(set(manifest) - seen)
    return report
