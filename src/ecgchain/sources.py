"""The catalogue: one entry per corpus *distribution*, not per corpus.

The distinction is not pedantry.  The same corpus reaches the box in more than
one packaging, and the packagings do not agree.  INCART is here twice: seventy-
five records as PhysioNet publishes it, seventy-four inside the Challenge 2021
bundle, under different record ids and at a different ADC gain.  PTB-XL and PTB
are here twice as well.  Key anything on the corpus name and
those pairs collapse into one; key on the distribution and the difference is a
row you can query.

Every field here is read from the distribution on disk -- the version and slug
from its index page, the licence from the licence file it ships -- and a corpus
that ships no licence file carries ``None`` rather than a guess.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = ["DATA_DIR", "PTBXL_DIR", "Source", "source", "sources"]

# The corpora are not in the repository and never will be: 53 GB of them sit on
# the box.  Override with ECGCHAIN_DATA_DIR when they move.
DATA_DIR = Path(os.environ.get("ECGCHAIN_DATA_DIR", Path.home() / "data"))

# PTB-XL as PhysioNet publishes it was downloaded for an earlier project and is
# read where it lies rather than copied.  Override with ECGCHAIN_PTBXL_DIR.
PTBXL_DIR = Path(os.environ.get("ECGCHAIN_PTBXL_DIR", Path.home() / "Developer/ptbxl5d/data"))

_PHYSIONET = "PhysioNet"
_CC_BY_4 = "CC BY 4.0"
_ODC_BY = "ODC-By 1.0"

# The eight sources the Challenge 2021 bundle ships under training/: the
# directory name the bundle uses, and the corpus it is a packaging of.  Two of
# them are packagings of corpora PhysioNet also publishes on their own, which
# is the whole reason the catalogue keys on the distribution.
_CHALLENGE_PARTITIONS = {
    "chapman_shaoxing": "chapman-shaoxing",
    "cpsc_2018": "cpsc-2018",
    "cpsc_2018_extra": "cpsc-2018-extra",
    "georgia": "georgia",
    "ningbo": "ningbo",
    "ptb": "ptb",
    "ptb-xl": "ptb-xl",
    "st_petersburg_incart": "incart",
}


@dataclass(frozen=True)
class Source:
    """One corpus as one publisher packages it, at one version."""

    source_id: str  # stable key: "<distribution>/<corpus>"
    corpus: str
    distribution: str
    version: str
    publisher: str
    licence: str | None  # what the distribution ships, None when it ships none
    slug: str  # the publisher's project slug, for the URL
    root: Path  # where the distribution is unpacked
    subdir: str  # "" when the corpus is the whole distribution
    manifest_name: str  # the publisher's checksum file, at the root
    manifest_prefix: str  # the prefix its paths carry for this corpus

    @property
    def directory(self) -> Path:
        """Where this corpus's own files are."""
        return self.root / self.subdir if self.subdir else self.root

    @property
    def manifest(self) -> Path:
        """The publisher's checksum file covering this corpus."""
        return self.root / self.manifest_name

    @property
    def url(self) -> str:
        return f"https://physionet.org/content/{self.slug}/{self.version}/"


def _challenge_source(partition: str) -> Source:
    return Source(
        source_id=f"challenge-2021/{partition}",
        corpus=_CHALLENGE_PARTITIONS[partition],
        distribution="challenge-2021",
        version="1.0.3",
        publisher=_PHYSIONET,
        licence=_CC_BY_4,
        slug="challenge-2021",
        root=DATA_DIR / "challenge2021",
        subdir=f"training/{partition}",
        manifest_name="SHA256SUMS.txt",
        manifest_prefix=f"training/{partition}/",
    )


def sources() -> tuple[Source, ...]:
    """Every distribution in the first delivery, in a stable order."""
    standalone = (
        Source(
            source_id="physionet/incartdb",
            corpus="incart",
            distribution="physionet",
            version="1.0.0",
            publisher=_PHYSIONET,
            licence=None,
            slug="incartdb",
            root=DATA_DIR / "incart",
            subdir="",
            manifest_name="SHA256SUMS.txt",
            manifest_prefix="",
        ),
        Source(
            source_id="physionet/ptb-xl",
            corpus="ptb-xl",
            distribution="physionet",
            version="1.0.3",
            publisher=_PHYSIONET,
            licence=_CC_BY_4,
            slug="ptb-xl",
            root=PTBXL_DIR,
            subdir="records500",
            manifest_name="SHA256SUMS.txt",
            manifest_prefix="records500/",
        ),
        Source(
            source_id="physionet/ludb",
            corpus="ludb",
            distribution="physionet",
            version="1.0.1",
            publisher=_PHYSIONET,
            licence=_ODC_BY,
            slug="ludb",
            root=DATA_DIR / "ludb",
            subdir="",
            manifest_name="SHA256SUMS.txt",
            manifest_prefix="",
        ),
        Source(
            source_id="physionet/ptbdb",
            corpus="ptb",
            distribution="physionet",
            version="1.0.0",
            publisher=_PHYSIONET,
            licence=None,
            slug="ptbdb",
            root=DATA_DIR / "ptbdb",
            subdir="",
            manifest_name="SHA256SUMS.txt",
            manifest_prefix="",
        ),
    )
    return tuple(_challenge_source(p) for p in _CHALLENGE_PARTITIONS) + standalone


def source(source_id: str) -> Source:
    """The entry with this id, or a KeyError naming what there is."""
    for entry in sources():
        if entry.source_id == source_id:
            return entry
    known = ", ".join(entry.source_id for entry in sources())
    raise KeyError(f"no source {source_id!r}; the catalogue holds {known}")
