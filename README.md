# DICOM Toolkit

Reusable utilities for controlled DICOM study modification, cloning, validation, and sending.

## Current Module

### MT-0020 DICOM Study Clone and Send Utility

Creates a new DICOM study from existing source objects by applying controlled demographic and study metadata changes, regenerating UIDs, and optionally sending the modified objects to a configured DICOM destination using DCM4CHE `storescu`.

## v0.1 Goals

- Process one study from a source folder
- Support future batch processing through CSV rows
- Apply controlled demographic and study metadata changes
- Generate a new Study Instance UID
- Generate a new Series Instance UID per source series
- Generate a new SOP Instance UID per object
- Never overwrite source files
- Write modified files to `output/modified`
- Produce an audit CSV of tag changes and generated UIDs
- Support dry-run and send modes
- Use pydicom for metadata editing
- Use DCM4CHE Toolkit for DICOM network sends

## Repository Layout

```text
config/
  destinations.example.json
  study-map.example.csv
docs/
  MT-0020-DICOM-Study-Clone-and-Send.md
input/
  .gitkeep
logs/
  .gitkeep
output/
  .gitkeep
scripts/
  Invoke-DicomModifySend.ps1
  modify_dicom_study.py
```

## Requirements

- Python 3.10+
- pydicom
- DCM4CHE Toolkit available locally
- PowerShell 5.1+ or PowerShell 7+

Install Python dependency:

```powershell
python -m pip install pydicom
```

## Basic Workflow

1. Copy source DICOM files into a folder under `input/`.
2. Copy `config/study-map.example.csv` to `config/study-map.csv` and update values.
3. Copy `config/destinations.example.json` to `config/destinations.json` and update the destination.
4. Run dry-run first.
5. Run modification.
6. Send with DCM4CHE `storescu` if desired.

## Example

```powershell
.\scripts\Invoke-DicomModifySend.ps1 `
  -StudyMap .\config\study-map.csv `
  -Destinations .\config\destinations.json `
  -Dcm4cheBin C:\Tools\dcm4che\bin `
  -DryRun
```

Then run without `-DryRun` to write modified files.

Use `-Send` to send modified files after successful generation.

## Safety Notes

- Source DICOM files are never modified in place.
- Generated UIDs are written to the audit log.
- Dry-run should be used before sending to a production destination.
- This utility is intended for controlled operational use where the user is authorized to modify and transmit DICOM objects.
