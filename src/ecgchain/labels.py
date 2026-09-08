"""Statements about a tracing, in the vocabulary they were written in.

The eight sources of the Challenge bundle carry SNOMED CT on the ``# Dx:`` line
of every header, so for them there is no mapping to build -- only a mapping to
check.  The four distributions PhysioNet publishes on their own carry none, and
that is not a gap to fill with a guess: PTB-XL's statements are SCP-ECG, PTB's
are free text, LUDB's are a spreadsheet of clinical categories.

Where a corpus reaches the box twice, the statement can travel the link the
screen established, and the row says so: a label propagated across a duplicate
link is marked as propagated and names the record it came from.  A reader can
drop every one of them with one predicate.

The code tables are read where the study that assembled them keeps them, and
their digests are checked before they are read.  Copying them here by hand
would make a fourth copy nobody could tell apart from the published ones.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from .manifest import sha256_file

__all__ = [
    "MAPPINGS",
    "MAPPINGS_DIR",
    "PARTITION_TO_SOURCE",
    "bundle_record_id",
    "label_map_table",
    "patient_table",
    "published_counts",
    "scored_table",
    "verified_mappings",
]

MAPPINGS_DIR = Path(
    os.environ.get(
        "ECGCHAIN_MAPPINGS_DIR",
        Path.home() / "Developer/ecg-conformal-shift/.claude/worktrees/ext-rotation/mappings",
    )
)

# The three published code tables, with the digest each was retrieved at.  The
# digests are recorded in that directory's NOTICE.md; they are repeated here so
# that a file which changed under us is refused rather than read.
MAPPINGS = {
    "dx_mapping_scored.csv": {
        "sha256": "fad13ad9f7ca230e7e6392ac8a264cb7cd157879525129f964c5f708eabb41d0",
        "source": "github.com/physionetchallenges/evaluation-2021",
        "retrieved": "2026-09-07",
        "licence": "BSD 2-Clause",
        "from_vocabulary": "Challenge 2021 scored class",
    },
    "AHA_SNOMED_mapping.csv": {
        "sha256": "23e0641aac859fd89ef8969402d844bb47bfb1caa6503bee451da359c5daeaae",
        "source": "github.com/UTU-Health-Research/dl-ecg-classifier",
        "retrieved": "2026-09-07",
        "licence": "MIT",
        "from_vocabulary": "AHA",
    },
    "ptbxlToSNOMED.csv": {
        "sha256": "63ae57a3a51387da39a6225a86ee2248b9cffc8d54215cbf177060ad59764d9f",
        "source": "PTB-XL+ 1.0.1, labels/mapping/ on PhysioNet",
        "retrieved": "2026-09-07",
        "licence": "CC BY 4.0",
        "from_vocabulary": "SCP-ECG",
    },
}

# The Challenge's per-partition count columns, and the distribution each names.
PARTITION_TO_SOURCE = {
    "CPSC": "challenge-2021/cpsc_2018",
    "CPSC_Extra": "challenge-2021/cpsc_2018_extra",
    "StPetersburg": "challenge-2021/st_petersburg_incart",
    "PTB": "challenge-2021/ptb",
    "PTB_XL": "challenge-2021/ptb-xl",
    "Georgia": "challenge-2021/georgia",
    "Chapman_Shaoxing": "challenge-2021/chapman_shaoxing",
    "Ningbo": "challenge-2021/ningbo",
}


def verified_mappings(directory: Path | None = None) -> dict[str, Path]:
    """The three code tables, each checked against the digest it was read at."""
    root = directory or MAPPINGS_DIR
    found: dict[str, Path] = {}
    for name, meta in MAPPINGS.items():
        path = root / name
        if not path.exists():
            raise FileNotFoundError(f"{path} is not there; see that directory's NOTICE.md")
        seen = sha256_file(path)
        if seen != meta["sha256"]:
            raise ValueError(f"{path} is {seen}, not the {meta['sha256']} it was read at")
        found[name] = path
    return found


def scored_table(directory: Path | None = None) -> pd.DataFrame:
    """The Challenge's scored-diagnosis table, with its per-partition counts."""
    path = verified_mappings(directory)["dx_mapping_scored.csv"]
    frame = pd.read_csv(path, encoding="utf-8-sig")
    frame["SNOMEDCTCode"] = frame["SNOMEDCTCode"].astype(str)
    return frame


def published_counts(directory: Path | None = None) -> dict[tuple[str, str], int]:
    """(distribution, SNOMED code) -> the count the organisers published."""
    frame = scored_table(directory)
    return {
        (source_id, str(row["SNOMEDCTCode"])): int(row[column])
        for _, row in frame.iterrows()
        for column, source_id in PARTITION_TO_SOURCE.items()
    }


def label_map_table(directory: Path | None = None) -> pd.DataFrame:
    """One row per published mapping, carrying the file it came from."""
    paths = verified_mappings(directory)
    rows: list[dict[str, object]] = []

    scored = pd.read_csv(paths["dx_mapping_scored.csv"], encoding="utf-8-sig")
    for _, row in scored.iterrows():
        rows.append(
            {
                "from_vocabulary": "Challenge 2021 scored class",
                "from_code": str(row["Abbreviation"]),
                "to_vocabulary": "SNOMED CT",
                "to_code": str(row["SNOMEDCTCode"]),
                "term": str(row["Dx"]),
                "map_source": "dx_mapping_scored.csv",
            }
        )

    aha = pd.read_csv(paths["AHA_SNOMED_mapping.csv"], encoding="utf-8-sig")
    for _, row in aha.iterrows():
        rows.append(
            {
                "from_vocabulary": "AHA",
                "from_code": str(row["AHA_Code"]),
                "to_vocabulary": "SNOMED CT",
                "to_code": str(row["SNOMEDCTCode"]),
                "term": str(row["Dx"]),
                "map_source": "AHA_SNOMED_mapping.csv",
            }
        )

    # PTB-XL+ names the clinical concept behind each SCP acronym in OMOP concept
    # ids, not SNOMED CT.  The row records what the file does say -- the concept
    # name -- and leaves the SNOMED column empty rather than passing an OMOP id
    # off as a SNOMED code.
    # Some of this file's rows carry more trailing commas than its header
    # declares columns, so the three columns that are read are named rather than
    # inferred, and the file is left exactly as published.
    scp = pd.read_csv(
        paths["ptbxlToSNOMED.csv"],
        encoding="utf-8-sig",
        header=0,
        usecols=[0, 1, 2],
        names=["Acronym", "Dx Statement", "id1"],
        engine="python",
    )
    for _, row in scp.iterrows():
        rows.append(
            {
                "from_vocabulary": "SCP-ECG",
                "from_code": str(row["Acronym"]).strip(),
                "to_vocabulary": "OMOP concept",
                "to_code": str(row["id1"]) if pd.notna(row.get("id1")) else None,
                "term": str(row["Dx Statement"]),
                "map_source": "ptbxlToSNOMED.csv",
            }
        )

    frame = pd.DataFrame(rows)
    meta = pd.DataFrame(
        [
            {
                "map_source": name,
                "map_sha256": fields["sha256"],
                "map_retrieved": fields["retrieved"],
                "map_licence": fields["licence"],
                "map_publisher": fields["source"],
            }
            for name, fields in MAPPINGS.items()
        ]
    )
    return frame.merge(meta, on="map_source", how="left")


def bundle_record_id(ecg_id: int) -> str:
    """PTB-XL's ecg_id as the Challenge bundle names it: HR plus five digits."""
    return f"HR{ecg_id:05d}"


def patient_table(source_id: str, directory: Path) -> pd.DataFrame:
    """The patients a distribution publishes, or an empty table when it publishes none.

    Only two of the twelve carry a patient key.  PTB-XL publishes one in its own
    database file; PTB files each recording under a patient directory.  The rest
    are silent, and silence is reported rather than replaced by one record per
    patient.
    """
    columns = ["patient_id", "source_id", "native_patient_id", "record_id", "age", "sex"]
    if source_id == "physionet/ptb-xl":
        database = directory.parent / "ptbxl_database.csv"
        if not database.exists():
            return pd.DataFrame(columns=columns)
        frame = pd.read_csv(database, usecols=["ecg_id", "patient_id", "age", "sex"])
        return pd.DataFrame(
            {
                "patient_id": source_id + ":" + frame["patient_id"].astype("Int64").astype(str),
                "source_id": source_id,
                "native_patient_id": frame["patient_id"].astype("Int64").astype(str),
                "record_id": source_id
                + ":"
                + frame["ecg_id"].map(lambda value: f"{int(value):05d}_hr"),
                "age": frame["age"],
                "sex": frame["sex"],
            }
        )
    if source_id == "physionet/ptbdb":
        rows = [
            {
                "patient_id": f"{source_id}:{header.parent.name}",
                "source_id": source_id,
                "native_patient_id": header.parent.name,
                "record_id": f"{source_id}:{header.stem}",
                "age": None,
                "sex": None,
            }
            for header in sorted(directory.rglob("*.hea"))
        ]
        return pd.DataFrame(rows, columns=columns)
    return pd.DataFrame(columns=columns)
