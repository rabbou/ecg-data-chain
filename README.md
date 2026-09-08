# ecg-data-chain

Twelve public ECG corpus distributions arrive in formats their publishers never
agreed on. Three spell their units `mv` and seven spell them `mV`; two declare
no units at all and leave a reader to supply them. One ships fifteen channels
where the rest ship twelve. Sampling rates run from 257 Hz to 1 kHz and record
lengths from five seconds to half an hour. Three of the twelve are second
packagings of a corpus already present under different record ids, renamed, and
two of the three rescaled to another ADC gain, so that matching on the record
id finds nothing.

This repository takes them as their publishers ship them and produces one
queryable database in which every tracing points back, in a single join, to the
file it came from. Nothing here trains or evaluates a model.

The delivery holds 110,876 records across 12 distributions, carrying 88,196
distinct fingerprints. The correlation sieve links a further 587 pairs that the
fingerprint does not collapse. All 240 cells of the PhysioNet Challenge 2021
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
290. For the other ten the `patient` table is empty, rather than holding one
invented patient per record.

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

One join, for any record in the delivery. The digest in that third column is
the one PhysioNet released, read from the `SHA256SUMS.txt` shipped with the
download. `tests/test_database.py` counts the joins in the query, so it cannot
gain a second hop without a test failing.

## Publishers' checksums

Five SHA-256 manifests cover the twelve distributions, one for the Challenge
bundle and four for the corpora PhysioNet publishes on their own. Re-hashing
the files here would only prove the copy is internally consistent, so the
digests are compared against the publisher's manifest instead.

Every one of the 222,301 files the delivery points at has its publisher's
declared digest recorded beside it. Of the 224,883 files the manifests list,
224,882 are recomputed and compared and 224,881 match. Four outcomes are kept
apart: files that match, files that differ, files the manifest lists and the
disk does not hold, files on disk the manifest never lists.

One file differs. `training/ningbo/g3/JS13118.mat` is 120,024 bytes, the same
length as its neighbours, and hashes to `bbd5fe83…` where PhysioNet published
`de32699c…`. Its size and header look ordinary, it parses to twelve canonical
leads, and it passes every quality check here. It is among the clean records
counted below. Only the publisher's manifest catches it; nothing in the signal
does.

Everything else the check reports is download residue. One manifest entry, a
`.DS_Store` in CPSC-2018, is listed and absent. 401 files on disk are unlisted:
394 `index.html` left by a recursive fetch, three `robots.txt`, the three
manifests that sit inside the directories they cover, and one `.DS_Store`.

## Finding the same tracing twice

Three sieves, cheapest first, each shrinking the work of the next.

1. The publisher's digest of the signal file. Two records whose signal files
   carry the same SHA-256 are the same bytes. It never fires on these corpora:
   no repackaging preserved the original bytes.
2. A digest of the first ten seconds of the twelve standard leads, quantised to
   ten microvolts. The quantum exists because the same recording arrives at
   different ADC gains, and ten microvolts is above the coarsest step any of
   these gains produces.
3. Correlation on what is left. Quadratic, so it runs on leftovers only, each
   side searched against the whole of the other, and it refuses any comparison
   larger than its cap.

| Corpus | Two packagings | Linked | By fingerprint | By correlation | Unmatched |
|---|---|---|---|---|---|
| INCART | 74 and 75 | 74 | 5 | 69 | `I36` |
| PTB | 516 and 549 | 516 | 0 | 516 | 33 |
| PTB-XL | 21,837 and 21,799 | 21,837 | 21,835 | 2 | none |

No record id is shared between two packagings of a corpus, so a screen keyed on
ids returns nothing on all three.

Every link records the scope it was found in. A repeat across two packagings of
one corpus and a repeat inside a single distribution are different findings,
and the second is the one a split has to respect, because splitting by patient
does not separate a recording from its own copy. Six of the twelve hold such
repeats: CPSC-2018 250 groups over 505 records, Georgia 92 over 186,
CPSC-extra 68 over 137, the bundled PTB-XL 34 over 70, Chapman-Shaoxing 13 over
26, Ningbo 3 over 6. The four distributions PhysioNet publishes on their own
hold none.

Thirty of those groups were opened to settle whether they are copies or second
recordings of one patient: twenty from CPSC-2018 and ten from Georgia, drawn
with a fixed seed. All thirty are identical sample for sample over the whole
record, with a maximum absolute difference of 0.0 and header comment blocks
that match line for line.

A split has to union `duplicate_link`, not `signal_group` alone: 587 of the
links come from the correlation sieve, and those pairs carry different
fingerprints by construction.

## Quality

Every record is judged on the first ten seconds of its twelve standard leads,
or on the whole record where it is shorter: absent leads, flat leads, leads
saturated at their own extreme for at least one per cent of the window, and
non-finite samples. No record in the twelve distributions is missing a standard
lead. 2,320 records fail a check, and Ningbo carries 1,583 of them, more than
the other eleven distributions together.

## Labels

The eight sources of the Challenge bundle carry SNOMED CT on the `# Dx:` line
of every header, so the mapping only has to be checked, not built. The 240
published cells are recomputed from the label table and agree.

Diagnoses are absent from the four distributions PhysioNet publishes on their
own. Three of them are packagings of a corpus whose other packaging carries
them, so a label is copied across the link to the record on the other side:
56,868 labels reach 22,389 records that way. Each row names the record it came
from and is kept in its own table, so a reader drops every copied label with
one predicate.

PTB-XL+'s SCP-ECG table is no help here. Its id columns hold OMOP concept ids
rather than SNOMED CT codes, so its 111 rows are recorded with `OMOP concept`
in `label_map.to_vocabulary` and an empty SNOMED code.

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
| `signal_group` | 110,876 | record, with the fingerprint group it belongs to |
| `duplicate_link` | 22,897 | pair of records the screen linked |

Parquet files. DuckDB reads them in process, so there is no server to run.

## Reproducing this

The corpora are not in the repository. Three paths are read from the
environment:

- `ECGCHAIN_DATA_DIR`, where the PhysioNet downloads are unpacked. Defaults to
  `~/data`.
- `ECGCHAIN_PTBXL_DIR`, PTB-XL 1.0.3 as PhysioNet publishes it, which sits
  outside the others. Defaults to `~/Developer/ptbxl5d/data`.
- `ECGCHAIN_MAPPINGS_DIR`, a directory holding the three published code tables:
  `dx_mapping_scored.csv` from `physionetchallenges/evaluation-2021`,
  `AHA_SNOMED_mapping.csv` from `UTU-Health-Research/dl-ecg-classifier`, and
  `ptbxlToSNOMED.csv` from PTB-XL+ 1.0.1 on PhysioNet. Fetch those three
  yourself; the default path is local to one machine.
  `src/ecgchain/labels.py` holds the SHA-256 each was retrieved at and refuses
  a file that differs.

```
uv sync --dev
uv run pytest -q -m "not data"        # 273 tests, no corpora needed
uv run pytest -q                      # with corpora on disk
```

Four passes read the corpora. Each runs under a memory cap and holds a lock, so
only one runs at a time on a machine with 15 GiB.

```
systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
    uv run python scripts/verify_manifests.py    # 10 min, every byte of 19 GB
systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
    uv run python scripts/scan_records.py        # 14 min, headers only
systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
    uv run python scripts/scan_quality.py        # 60 min, every signal
systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G \
    uv run python scripts/build_database.py      # 43 min, writes the Parquet
uv run python scripts/build_labels.py            # seconds, reads the Parquet
                                                 # and the patient metadata
```

`scan_quality.py --reuse-digests` screens again from the cached fingerprints
without reading the signals a second time.

## Limits

MIMIC-IV-ECG is not here. Nothing in this repository reads it.

`split` and `signal_window` are named in the code as deferred and are not in
the delivery at all. Drawing a split is the reader's decision, and the delivery
points at signal files rather than serving arrays.

The ten-microvolt quantum is this repository's choice, not a published
threshold: two recordings that differ by less than that get the same
fingerprint, and the correlation sieve catches the pairs it misses.

Vendor XML is absent. Chapman-Shaoxing came out of a GE MUSE system and
PhysioNet redistributes it converted to WFDB, so there is no MUSE, Philips,
SCP-ECG or ISHNE file here to write a parser against.

## Gates

`ruff check`, `ruff format --check`, `mypy` and `pytest`, on every push to
`main` and on every pull request. Tests marked `data` need the corpora and are
skipped where they are absent.
