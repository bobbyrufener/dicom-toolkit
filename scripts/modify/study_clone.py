#!/usr/bin/env python3
"""
MT-0020 DICOM Study Clone and Send Utility

Reads DICOM files from a source folder, applies controlled demographic/study
metadata changes, regenerates Study/Series/SOP UIDs, and writes modified copies
without changing source files.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

try:
    import pydicom
    from pydicom.uid import generate_uid
except ImportError as exc:
    print("ERROR: pydicom is required. Install with: python -m pip install pydicom", file=sys.stderr)
    raise SystemExit(2) from exc


DICOM_TAG_UPDATES = {
    "NewPatientName": "PatientName",
    "NewPatientID": "PatientID",
    "NewDOB": "PatientBirthDate",
    "NewSex": "PatientSex",
    "NewAccession": "AccessionNumber",
    "NewStudyDescription": "StudyDescription",
    "NewStudyID": "StudyID",
}


REQUIRED_COLUMNS = [
    "SourceFolder",
    "OutputFolder",
    "NewPatientName",
    "NewPatientID",
    "NewDOB",
    "NewSex",
    "NewAccession",
    "NewStudyDescription",
    "NewStudyID",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clone a DICOM study with modified demographics/study information.")
    parser.add_argument("--study-map", required=True, help="Path to study-map CSV.")
    parser.add_argument("--row-index", type=int, default=0, help="Zero-based row index to process from study-map CSV.")
    parser.add_argument("--audit-log", required=True, help="Path to audit CSV to write.")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate changes without writing modified DICOM files.")
    parser.add_argument("--recursive", action="store_true", default=True, help="Search source folder recursively. Default: true.")
    return parser.parse_args()


def load_study_row(study_map_path: Path, row_index: int) -> Dict[str, str]:
    if not study_map_path.exists():
        raise FileNotFoundError(f"Study map not found: {study_map_path}")

    with study_map_path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise ValueError("Study map CSV has no data rows.")

    if row_index < 0 or row_index >= len(rows):
        raise IndexError(f"Row index {row_index} is out of range. CSV has {len(rows)} rows.")

    row = {key: (value or "").strip() for key, value in rows[row_index].items()}
    missing = [column for column in REQUIRED_COLUMNS if column not in row or not row[column]]
    if missing:
        raise ValueError(f"Study map row is missing required values: {', '.join(missing)}")

    return row


def iter_source_files(source_folder: Path, recursive: bool = True) -> Iterable[Path]:
    pattern = "**/*" if recursive else "*"
    for path in source_folder.glob(pattern):
        if path.is_file():
            yield path


def read_dicom(path: Path):
    try:
        return pydicom.dcmread(str(path), force=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Unable to read DICOM file {path}: {exc}") from exc


def safe_original_value(dataset, keyword: str) -> str:
    return str(getattr(dataset, keyword, ""))


def build_uid_maps(datasets: List[Tuple[Path, object]]) -> Tuple[str, Dict[str, str], Dict[str, str]]:
    new_study_uid = generate_uid()
    series_uid_map: Dict[str, str] = {}
    sop_uid_map: Dict[str, str] = {}

    for _, ds in datasets:
        original_series_uid = str(getattr(ds, "SeriesInstanceUID", ""))
        original_sop_uid = str(getattr(ds, "SOPInstanceUID", ""))

        if original_series_uid and original_series_uid not in series_uid_map:
            series_uid_map[original_series_uid] = generate_uid()

        if original_sop_uid and original_sop_uid not in sop_uid_map:
            sop_uid_map[original_sop_uid] = generate_uid()

    return new_study_uid, series_uid_map, sop_uid_map


def relative_output_path(source_folder: Path, output_folder: Path, source_file: Path) -> Path:
    try:
        relative = source_file.relative_to(source_folder)
    except ValueError:
        relative = Path(source_file.name)
    return output_folder / relative


def process_study(row: Dict[str, str], audit_log: Path, dry_run: bool, recursive: bool) -> Dict[str, int | str]:
    source_folder = Path(row["SourceFolder"]).resolve()
    output_folder = Path(row["OutputFolder"]).resolve()

    if not source_folder.exists():
        raise FileNotFoundError(f"Source folder not found: {source_folder}")

    source_files = list(iter_source_files(source_folder, recursive=recursive))
    if not source_files:
        raise ValueError(f"No files found in source folder: {source_folder}")

    datasets: List[Tuple[Path, object]] = []
    skipped: List[Tuple[Path, str]] = []

    for file_path in source_files:
        try:
            ds = read_dicom(file_path)
            if not hasattr(ds, "SOPInstanceUID"):
                skipped.append((file_path, "Missing SOPInstanceUID"))
                continue
            datasets.append((file_path, ds))
        except Exception as exc:  # noqa: BLE001
            skipped.append((file_path, str(exc)))

    if not datasets:
        raise ValueError("No readable DICOM instances were found.")

    new_study_uid, series_uid_map, sop_uid_map = build_uid_maps(datasets)

    audit_log.parent.mkdir(parents=True, exist_ok=True)
    if not dry_run:
        output_folder.mkdir(parents=True, exist_ok=True)

    audit_fields = [
        "Timestamp",
        "DryRun",
        "SourceFile",
        "OutputFile",
        "OriginalStudyInstanceUID",
        "NewStudyInstanceUID",
        "OriginalSeriesInstanceUID",
        "NewSeriesInstanceUID",
        "OriginalSOPInstanceUID",
        "NewSOPInstanceUID",
        "PatientNameBefore",
        "PatientNameAfter",
        "PatientIDBefore",
        "PatientIDAfter",
        "AccessionBefore",
        "AccessionAfter",
        "Status",
        "Message",
    ]

    processed = 0
    written = 0

    with audit_log.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=audit_fields)
        writer.writeheader()

        for source_file, ds in datasets:
            output_file = relative_output_path(source_folder, output_folder, source_file)
            original_study_uid = safe_original_value(ds, "StudyInstanceUID")
            original_series_uid = safe_original_value(ds, "SeriesInstanceUID")
            original_sop_uid = safe_original_value(ds, "SOPInstanceUID")

            new_series_uid = series_uid_map.get(original_series_uid, generate_uid())
            new_sop_uid = sop_uid_map.get(original_sop_uid, generate_uid())

            audit_row = {
                "Timestamp": datetime.now().isoformat(timespec="seconds"),
                "DryRun": str(dry_run),
                "SourceFile": str(source_file),
                "OutputFile": str(output_file),
                "OriginalStudyInstanceUID": original_study_uid,
                "NewStudyInstanceUID": new_study_uid,
                "OriginalSeriesInstanceUID": original_series_uid,
                "NewSeriesInstanceUID": new_series_uid,
                "OriginalSOPInstanceUID": original_sop_uid,
                "NewSOPInstanceUID": new_sop_uid,
                "PatientNameBefore": safe_original_value(ds, "PatientName"),
                "PatientNameAfter": row["NewPatientName"],
                "PatientIDBefore": safe_original_value(ds, "PatientID"),
                "PatientIDAfter": row["NewPatientID"],
                "AccessionBefore": safe_original_value(ds, "AccessionNumber"),
                "AccessionAfter": row["NewAccession"],
                "Status": "DRY_RUN" if dry_run else "WRITTEN",
                "Message": "",
            }

            for csv_column, dicom_keyword in DICOM_TAG_UPDATES.items():
                setattr(ds, dicom_keyword, row[csv_column])

            ds.StudyInstanceUID = new_study_uid
            ds.SeriesInstanceUID = new_series_uid
            ds.SOPInstanceUID = new_sop_uid
            ds.file_meta.MediaStorageSOPInstanceUID = new_sop_uid

            processed += 1

            if not dry_run:
                output_file.parent.mkdir(parents=True, exist_ok=True)
                ds.save_as(str(output_file), write_like_original=False)
                written += 1

            writer.writerow(audit_row)

        for skipped_file, reason in skipped:
            writer.writerow({
                "Timestamp": datetime.now().isoformat(timespec="seconds"),
                "DryRun": str(dry_run),
                "SourceFile": str(skipped_file),
                "OutputFile": "",
                "OriginalStudyInstanceUID": "",
                "NewStudyInstanceUID": new_study_uid,
                "OriginalSeriesInstanceUID": "",
                "NewSeriesInstanceUID": "",
                "OriginalSOPInstanceUID": "",
                "NewSOPInstanceUID": "",
                "PatientNameBefore": "",
                "PatientNameAfter": row["NewPatientName"],
                "PatientIDBefore": "",
                "PatientIDAfter": row["NewPatientID"],
                "AccessionBefore": "",
                "AccessionAfter": row["NewAccession"],
                "Status": "SKIPPED",
                "Message": reason,
            })

    return {
        "source_folder": str(source_folder),
        "output_folder": str(output_folder),
        "audit_log": str(audit_log),
        "processed": processed,
        "written": written,
        "skipped": len(skipped),
        "new_study_uid": new_study_uid,
        "dry_run": str(dry_run),
    }


def main() -> int:
    args = parse_args()
    try:
        row = load_study_row(Path(args.study_map), args.row_index)
        result = process_study(row, Path(args.audit_log), args.dry_run, args.recursive)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
