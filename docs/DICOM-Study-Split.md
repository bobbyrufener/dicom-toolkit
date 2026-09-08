# DICOM Study Split Service

The study split service creates two or more independent studies from selected
series in one source study. Source files are read-only; output is written to a
separate folder.

For every output group, the service generates:

- one new Study Instance UID;
- one new Series Instance UID for each selected source series; and
- one new SOP Instance UID for each copied object.

Matching UID values in nested DICOM sequences are rewritten from the same maps.
This preserves references between copied objects when the referenced objects are
included in the same split group. File Meta Information is synchronized with the
new SOP Instance UID.

## Configure a split

Copy `config/study-split.example.json` and assign every source Series Instance
UID to exactly one output group. Manifest paths are relative to the manifest.
Optional accession number and study description values can distinguish the new
orders without changing patient demographics.

## Validate first

```bash
dicom-toolkit split-study --manifest config/study-split.json --dry-run --audit-json logs/split-dry-run.json
```

The command rejects mixed source studies, duplicate series assignments, unknown
series UIDs, unassigned source series, nested output folders, and existing
output files. Use `--allow-unassigned` only when intentionally leaving some
series behind.

## Write the split studies

```bash
dicom-toolkit split-study --manifest config/study-split.json --audit-json logs/split-audit.json
```

Use `--overwrite` only when intentionally replacing an earlier output. Validate
the output in a non-production destination before importing it into a PACS/VNA.
