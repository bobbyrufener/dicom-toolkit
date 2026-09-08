from __future__ import annotations

from pathlib import Path

import pydicom
import pytest
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage

from dicom_toolkit.modify import SplitGroup, SplitManifest, StudySplitService


STUDY_UID = "1.2.826.0.1.3680043.10.999.1"
SERIES_A = "1.2.826.0.1.3680043.10.999.2"
SERIES_B = "1.2.826.0.1.3680043.10.999.3"
SOP_A = "1.2.826.0.1.3680043.10.999.4"
SOP_B = "1.2.826.0.1.3680043.10.999.5"


def _write_instance(path: Path, series_uid: str, sop_uid: str) -> None:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(path, {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = SecondaryCaptureImageStorage
    dataset.SOPInstanceUID = sop_uid
    dataset.StudyInstanceUID = STUDY_UID
    dataset.SeriesInstanceUID = series_uid
    dataset.PatientName = "SPLIT^TEST"
    dataset.PatientID = "12345"
    reference = Dataset()
    reference.ReferencedSOPInstanceUID = sop_uid
    reference.StudyInstanceUID = STUDY_UID
    dataset.ReferencedImageSequence = Sequence([reference])
    dataset.save_as(path, enforce_file_format=True)


def _uid_factory():
    values = iter(
        [
            "1.2.826.0.1.3680043.10.999.101",
            "1.2.826.0.1.3680043.10.999.102",
            "1.2.826.0.1.3680043.10.999.103",
            "1.2.826.0.1.3680043.10.999.104",
            "1.2.826.0.1.3680043.10.999.105",
            "1.2.826.0.1.3680043.10.999.106",
        ]
    )
    return lambda: next(values)


def test_split_creates_independent_studies_and_updates_references(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_instance(source / "a.dcm", SERIES_A, SOP_A)
    _write_instance(source / "b.dcm", SERIES_B, SOP_B)
    manifest = SplitManifest(
        source,
        tmp_path / "output",
        (
            SplitGroup("a", frozenset({SERIES_A}), accession_number="A-NEW"),
            SplitGroup("b", frozenset({SERIES_B}), study_description="Second study"),
        ),
    )

    result = StudySplitService(_uid_factory()).split(manifest)
    output_a = pydicom.dcmread(tmp_path / "output" / "a" / "a.dcm")
    output_b = pydicom.dcmread(tmp_path / "output" / "b" / "b.dcm")

    assert output_a.StudyInstanceUID != output_b.StudyInstanceUID
    assert output_a.StudyInstanceUID != STUDY_UID
    assert output_a.SeriesInstanceUID != SERIES_A
    assert output_a.SOPInstanceUID != SOP_A
    assert output_a.file_meta.MediaStorageSOPInstanceUID == output_a.SOPInstanceUID
    assert output_a.ReferencedImageSequence[0].ReferencedSOPInstanceUID == output_a.SOPInstanceUID
    assert output_a.ReferencedImageSequence[0].StudyInstanceUID == output_a.StudyInstanceUID
    assert output_a.AccessionNumber == "A-NEW"
    assert output_b.StudyDescription == "Second study"
    assert len(result.written_files) == 2


def test_rejects_series_assigned_to_multiple_groups(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    manifest = SplitManifest(
        source,
        tmp_path / "output",
        (SplitGroup("a", frozenset({SERIES_A})), SplitGroup("b", frozenset({SERIES_A}))),
    )

    with pytest.raises(ValueError, match="only one split group"):
        StudySplitService().split(manifest)


def test_rejects_unassigned_series_by_default(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_instance(source / "a.dcm", SERIES_A, SOP_A)
    _write_instance(source / "b.dcm", SERIES_B, SOP_B)
    manifest = SplitManifest(source, tmp_path / "output", (SplitGroup("a", frozenset({SERIES_A})),))

    with pytest.raises(ValueError, match="not assigned"):
        StudySplitService().split(manifest)


def test_dry_run_does_not_create_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_instance(source / "a.dcm", SERIES_A, SOP_A)
    output = tmp_path / "output"
    manifest = SplitManifest(source, output, (SplitGroup("a", frozenset({SERIES_A})),))

    result = StudySplitService(_uid_factory()).split(manifest, dry_run=True)

    assert not output.exists()
    assert result.written_files == [output / "a" / "a.dcm"]


def test_rejects_duplicate_sop_instance_uids(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_instance(source / "a.dcm", SERIES_A, SOP_A)
    _write_instance(source / "b.dcm", SERIES_B, SOP_A)
    manifest = SplitManifest(
        source,
        tmp_path / "output",
        (
            SplitGroup("a", frozenset({SERIES_A})),
            SplitGroup("b", frozenset({SERIES_B})),
        ),
    )

    with pytest.raises(ValueError, match="duplicate SOPInstanceUID"):
        StudySplitService().split(manifest)
