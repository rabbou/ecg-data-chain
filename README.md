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

The first delivery is twelve distributions: the eight sources of the Challenge
2021 bundle, plus INCART, LUDB, PTB and PTB-XL as PhysioNet publishes them.

## What the headers are not asked to supply

Units are read from the header text, not from the reader. Two of the twelve
distributions — INCART and PTB as PhysioNet publishes them — declare no units
at all: their signal lines stop at the gain, and `wfdb` fills in `mV` on their
behalf. Three of the bundle's eight sources spell it `mv` and five spell it
`mV`. None of that is normalised away; the millivolt test is the one that
ignores case.

## Finding the same tracing twice

Three sieves, cheapest first, each shrinking the work of the next: the
publisher's digest of the signal file, then a digest of the first ten seconds
of the twelve standard leads quantised to ten microvolts, then correlation on
what is left. The quantised digest exists because the same recording reaches
the box at different ADC gains — INCART is 306 units per millivolt as
PhysioNet publishes it and 1000 in the bundle — and the correlation sieve
exists because a quantum does not save a sample sitting on a rounding
boundary.

## Running it

The corpora are not in the repository. Point `ECGCHAIN_DATA_DIR` at wherever
they are unpacked; it defaults to `~/data`.

```
uv sync --dev
uv run pytest -q -m "not data"        # everything that does not need corpora
uv run pytest -q                      # everything, with corpora on disk
```

Three passes are heavy — verifying the manifests reads every byte of every
corpus, and the quality sweep reads every sample of every record — so they run
under a memory cap, one at a time:

```
systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
    uv run python scripts/verify_manifests.py
```

```
systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
    uv run python scripts/scan_records.py
```

```
systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
    uv run python scripts/scan_quality.py
```

## Gates

`ruff check`, `ruff format --check`, `mypy` and `pytest`, on every push and
pull request. Tests marked `data` need the corpora and are skipped where they
are absent.
