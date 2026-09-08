# ecg-data-chain

Twelve public ECG corpora arrive in formats that do not agree with each other.
This repository takes them as their publishers ship them and produces one
queryable database in which every tracing points back, in a single join, to the
file it came from.

It stops at the labelled database. There is no model here, and no measurement
of one.

## Where it starts

Not at the signal: at the publisher's checksums. Every corpus in the first
delivery ships a `SHA256SUMS.txt` written by whoever released it. Hashing the
files ourselves would prove the box agrees with itself; checking them against
the publisher's file proves the box holds what was released.

## What the catalogue keys on

A corpus reaches the box in more than one packaging, and the packagings do not
agree. INCART is here twice — 75 records as PhysioNet publishes it, 74 inside
the PhysioNet Challenge 2021 bundle, under different record ids. PTB is here
twice as well. So the key is the distribution, not the corpus name, and the
relation between two packagings of the same tracing is something to establish
rather than assume.

The first delivery is eleven distributions: the eight sources of the Challenge
2021 bundle, plus INCART, LUDB and PTB as PhysioNet publishes them.

## Running it

The corpora are not in the repository. Point `ECGCHAIN_DATA_DIR` at wherever
they are unpacked; it defaults to `~/data`.

```
uv sync --dev
uv run pytest -q -m "not data"        # everything that does not need corpora
uv run pytest -q                      # everything, with corpora on disk
```

Verifying the manifests reads every byte of every corpus, so it runs under a
memory cap:

```
systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
    uv run python scripts/verify_manifests.py
```

## Gates

`ruff check`, `ruff format --check`, `mypy` and `pytest`, on every push and
pull request. Tests marked `data` need the corpora and are skipped where they
are absent.
