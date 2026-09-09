# ecg-data-chain

Twelve public ECG corpus distributions arrive in formats their publishers never
agreed on. Three spell their units `mv` and seven spell them `mV`; two declare
no units at all and leave a reader to supply them. One ships fifteen channels
where the rest ship twelve. Sampling rates run from 257 Hz to 1 kHz and record
lengths from five seconds to half an hour. Three of the twelve are second
packagings of a corpus already present, renamed to different record ids, and
two of the three rescaled to another ADC gain.

This repository takes them as their publishers ship them and produces one
queryable database in which every tracing points back, in a single join, to the
file it came from. Nothing here trains or evaluates a model.

The delivery holds 110,876 records across 12 distributions, holding 87,609
distinct tracings between them. All 240 cells of the PhysioNet Challenge 2021
scored-diagnosis table, thirty classes across eight partitions, are recomputed
here from the label table and agree with the counts the organisers published.

## Corpora

| Distribution | Records | Leads | Rate | Units in the header | Licence in the download |
|---|---|---|---|---|---|
| challenge-2021/ningbo | 34,905 | 12 | 500 Hz | `mV` | CC BY 4.0 |
| challenge-2021/ptb-xl | 21,837 | 12 | 500 Hz | `mv` | CC BY 4.0 |
| physionet/ptb-xl | 21,799 | 12 | 500 Hz | `mV` | CC BY 4.0 |
| challenge-2021/georgia | 10,344 | 12 | 500 Hz | `mV` | CC BY 4.0 |
| challenge-2021/chapman_shaoxing | 10,247 | 12 | 500 Hz | `mV` | CC BY 4.0 |
| challenge-2021/cpsc_2018 | 6,877 | 12 | 500 Hz | `mV` | CC BY 4.0 |
| challenge-2021/cpsc_2018_extra | 3,453 | 12 | 500 Hz | `mV` | CC BY 4.0 |
| physionet/ptbdb | 549 | 15 | 1 kHz | none | none |
| challenge-2021/ptb | 516 | 12 | 1 kHz | `mv` | CC BY 4.0 |
| physionet/ludb | 200 | 12 | 500 Hz | `mV` | ODC-By 1.0 |
| physionet/incartdb | 75 | 12 | 257 Hz | none | none |
| challenge-2021/st_petersburg_incart | 74 | 12 | 257 Hz | `mv` | CC BY 4.0 |

The last column is what the download contains. INCART and PTB ship no licence
file; their PhysioNet project pages state the terms.

The key is the distribution, not the corpus name. INCART, PTB and PTB-XL each
appear twice, and the two copies of each disagree on their record count and
their record ids. INCART and PTB also disagree on ADC gain: INCART's PhysioNet
packaging carries twelve distinct gains from 240 to 1063 units per millivolt,
varying by record and by lead, where the bundle rescales every record to 1,000;
PTB goes from 2,000 to 1,000 the same way. Key on the corpus name and the six
rows collapse into three.

Two distributions publish a patient key: PTB-XL's 18,869 patients and PTB's
290. The `patient` table has no rows for the other ten.

## Where a tracing comes from

```sql
SELECT r.record_id, f.relative_path, f.sha256_declared
FROM record r JOIN source_file f ON f.file_id = r.signal_file_id
WHERE r.record_id = ?
```

```
challenge-2021/chapman_shaoxing:JS02202
g3/JS02202.mat
cd1e882875df52351103b3e9611133a5efad0fedfd93437b82ca53900a42b580
```

That query is one join, and it works for any record in the delivery. The digest
in the third column is the one PhysioNet released, read from the
`SHA256SUMS.txt` shipped with the download. `tests/test_database.py` counts the
joins in the query, so it cannot gain a second hop without a test failing.

## Publishers' checksums

Five SHA-256 manifests cover the twelve distributions, one for the Challenge
bundle and four for the corpora PhysioNet publishes on their own. Storing a
digest of our own would prove the copy is internally consistent. Every file is
re-hashed and compared against the digest its publisher declared, which is what
proves it is the copy the publisher released.

Every one of the 222,301 files the delivery points at has its publisher's
declared digest recorded beside it. Of the 224,883 files the manifests list,
224,882 are re-hashed and compared and 224,881 match. The check reports four
outcomes separately: match, differ, listed but absent, present but unlisted.

One file differs. `training/ningbo/g3/JS13118.mat` hashes to a value PhysioNet
did not publish, against a declared
`de32699cbd677b507177b60fa06125e55a935c8ef69daa0f8e8171b06d1b6f5a`; the ledger
records both digests side by side. The file is the same length as its
neighbours, it parses to twelve canonical leads, and it passes every check in
the Quality section below. Nothing in the record itself shows the difference.
The manifest is the only check that catches it.

Everything else the check reports is download residue. One manifest entry, a
`.DS_Store` in CPSC-2018, is listed and absent. 401 files on disk are unlisted:
394 `index.html` left by a recursive fetch, three `robots.txt`, the three
manifests that sit inside the directories they cover, and one `.DS_Store`.

## Finding the same tracing twice

Three sieves run in order, cheapest first. Each one shrinks the work the next
has to do.

1. The publisher's digest of the signal file. Two records whose signal files
   carry the same SHA-256 are the same bytes. It fires on none of these
   corpora, because no repackaging preserved the original bytes.
2. A digest of the first ten seconds of the twelve standard leads, quantised to
   ten microvolts. The quantum exists because the same recording arrives at
   different ADC gains, and ten microvolts is above the coarsest step in the
   delivery, LUDB's 4.20 microvolts at a gain of 238.
3. Correlation on what is left. Quadratic, so it runs on leftovers only, each
   side searched against the whole of the other, and it refuses any comparison
   larger than its cap.

| Corpus | Two packagings | Linked | By fingerprint | By correlation | Unmatched |
|---|---|---|---|---|---|
| INCART | 74 and 75 | 74 | 5 | 69 | 1 |
| PTB | 516 and 549 | 516 | 0 | 516 | 33 |
| PTB-XL | 21,837 and 21,799 | 21,837 | 21,835 | 2 | 0 |

The unmatched INCART record is `physionet/incartdb:I36`. PTB-XL's row holds a
one-to-many: 21,837 links over 21,799 original records, because 38 of the
bundle's records repeat a tracing the bundle already carries.

No record id is shared between two packagings of a corpus. PTB-XL is the
exception in one direction: the bundle names its records `HR` plus the
zero-padded PTB-XL `ecg_id`, and that convention recovers all 21,799 originals
on its own. The signal screen is run against it rather than in place of it, and
the two agree. INCART and PTB have no such convention, and for them the signal
is the only route.

`signal_group` closes over every sieve. 587 of the links come from correlation,
including all 516 of PTB's, and a group built from fingerprints alone would put
a record and its own copy on opposite sides of a fold. A split drawn on
`signal_group_id` needs no further union, and a test checks that no link in
`duplicate_link` crosses two groups.

Every link also records its scope. A repeat across two packagings of one corpus
and a repeat inside a single distribution are different findings, and the
second is the one a split has to respect, because splitting by patient does not
separate a recording from its own copy. Six of the twelve hold such repeats:
CPSC-2018 250 groups over 505 records, Georgia 92 over 186, CPSC-extra 68 over
137, the bundled PTB-XL 34 over 70, Chapman-Shaoxing 13 over 26, Ningbo 3 over
6. The four distributions PhysioNet publishes on their own hold none.

Thirty of those groups were opened by `scripts/check_intra_duplicates.py` to
settle whether they are copies or second recordings of one patient: twenty from
CPSC-2018 and ten from Georgia, drawn with a fixed seed. All thirty are
identical sample for sample over the whole record, with a maximum absolute
difference of 0.0 and header comment blocks that match line for line.

## Quality

Every record is judged on the first ten seconds of its twelve standard leads,
or on the whole record where it is shorter: absent leads, flat leads, leads
saturated at their own extreme for at least one per cent of the window, and
non-finite samples. No record in the twelve distributions is missing a standard
lead. 2,320 records fail a check, and Ningbo carries 1,583 of them, more than
the other eleven distributions together.

## Labels

The eight sources of the Challenge bundle carry SNOMED CT on the `# Dx:` line
of every header, so the mapping only has to be checked. The 240 published cells
are recomputed from the label table and agree.

Diagnoses are absent from the four distributions PhysioNet publishes on their
own. Three of them are packagings of a corpus whose other packaging carries
them, so a label is copied across the link to the record on the other side:
56,868 labels reach 22,389 records that way. Each row names the record it came
from and is kept in its own table, so a reader drops every copied label with
one predicate.

PTB-XL+'s SCP-ECG table is no help here. Its id columns hold OMOP concept ids
rather than SNOMED CT codes, so its 111 rows carry `OMOP concept` in
`label_map.to_vocabulary` and an OMOP id in `to_code`. Nothing here maps them
onward to SNOMED.

The three published code tables are read from a local copy, each checked
against the digest it was retrieved at before it is read.

## Tables

| Table | Rows | One row per |
|---|---|---|
| `source` | 12 | corpus distribution |
| `source_file` | 222,301 | header or signal file as its publisher shipped it |
| `record` | 110,876 | tracing as its corpus ships it |
| `lead` | 1,332,159 | channel of a tracing |
| `label` | 181,817 | statement its corpus asserted |
| `label_propagated` | 56,868 | statement copied across a link |
| `label_map` | 164 | published mapping between vocabularies |
| `patient` | 22,348 | record, with the patient published for it |
| `quality` | 110,876 | tracing judged |
| `signal_group` | 110,876 | record, with the group holding its tracing and its own fingerprint |
| `duplicate_link` | 22,908 | pair of records the screen linked |

The tables are Parquet files. DuckDB reads them in process, so there is no
server to run.

## Rebuilding the delivery

Neither the corpora nor the Parquet is in the repository. The corpora are
downloaded from PhysioNet; the tables are rebuilt from them by the commands
below, in about two hours. Three paths are read from the environment:

- `ECGCHAIN_DATA_DIR`, where the PhysioNet downloads are unpacked. Defaults to
  `~/data`.
- `ECGCHAIN_PTBXL_DIR`, PTB-XL 1.0.3 as PhysioNet publishes it, which sits
  outside the others. Defaults to `~/Developer/ptbxl5d/data`.
- `ECGCHAIN_MAPPINGS_DIR`, a directory holding the three published code tables:
  `dx_mapping_scored.csv` from `physionetchallenges/evaluation-2021`,
  `AHA_SNOMED_mapping.csv` from `UTU-Health-Research/dl-ecg-classifier`, and
  `ptbxlToSNOMED.csv` from PTB-XL+ 1.0.1 on PhysioNet. Fetch those three
  yourself and point the variable at them; its default is a scratch directory
  on the author's machine. `src/ecgchain/labels.py` holds the SHA-256 each was
  retrieved at and refuses a file that differs.

```
uv sync --dev
uv run pytest -q -m "not data"        # 276 tests, no corpora needed
uv run pytest -q                      # with corpora on disk
```

Four passes read the signals. Each runs under a memory cap and holds a lock, so
only one runs at a time on a machine with 15 GiB.

```
systemd-run --user --scope -p MemoryMax=3G -p MemoryHigh=2500M \
    uv run python scripts/verify_manifests.py    # 10 min, every byte of 19 GB
systemd-run --user --scope -p MemoryMax=3G -p MemoryHigh=2500M \
    uv run python scripts/scan_records.py        # 14 min, headers only
systemd-run --user --scope -p MemoryMax=3G -p MemoryHigh=2500M \
    uv run python scripts/scan_quality.py        # 55 min, every signal
systemd-run --user --scope -p MemoryMax=3G -p MemoryHigh=2500M \
    uv run python scripts/build_database.py      # 43 min, writes the Parquet
uv run python scripts/build_labels.py            # seconds, reads the Parquet
                                                 # and the patient metadata
```

`scan_quality.py --reuse-digests` screens again from the cached fingerprints
without reading the signals a second time, in twelve minutes.

The caps are set on what these passes hold, not on what they read. Profiled on
one pair of packagings, the screen holds 272 MB resident and 0.16 GB of
anonymous memory; the cgroup counter reaches 0.88 GB for the same run, and the
difference is page cache from the corpus files. A pure hashing pass reaches the
same 2.44 GB on that counter as a full screen does, which is what page cache
looks like rather than a memory requirement.

## Limits

MIMIC-IV-ECG is not here, and nothing in this repository reads it.

`split` and `signal_window` are named in the code as deferred and hold no rows.
Drawing a split is the reader's decision, and the delivery points at signal
files.

The ten-microvolt quantum is this repository's choice. No published threshold
sets it, two recordings that differ by less than that get the same fingerprint,
and the correlation sieve catches the pairs the fingerprint misses.

Vendor XML is absent. Chapman-Shaoxing came out of a GE MUSE system and
PhysioNet redistributes it converted to WFDB, so there is no MUSE, Philips,
SCP-ECG or ISHNE file here to write a parser against.

## Gates

`ruff check`, `ruff format --check`, `mypy` and `pytest`, on every push to
`main` and on every pull request. Tests marked `data` need the corpora and are
skipped where they are absent.
