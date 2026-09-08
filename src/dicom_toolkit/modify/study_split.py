"""Split selected series from one DICOM study into conflict-free studies."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pydicom
from pydicom.dataset import Dataset
from pydicom.multival import MultiValue
from pydicom.uid import UID, generate_uid


@dataclass(frozen=True)
class SplitGroup:
    """A set of source series that will become one new study."""

    name: str
    series_instance_uids: frozenset[str]
    accession_number: str | None = None
    study_description: str | None = None

    @classmethod
    def from_dict(cls, value: dict) -> "SplitGroup":
        return cls(
            name=str(value["name"]).strip(),
            series_instance_uids=frozenset(str(uid).strip() for uid in value["series_instance_uids"]),
            accession_number=_optional_string(value.get("accession_number")),
            study_description=_optional_string(value.get("study_description")),
        )


@dataclass(frozen=True)
class SplitManifest:
    source_folder: Path
    output_folder: Path
    groups: tuple[SplitGroup, ...]

    @classmethod
    def from_json(cls, path: Path) -> "SplitManifest":
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        base = path.resolve().parent
        return cls(
            _resolve_from(base, value["source_folder"]),
            _resolve_from(base, value["output_folder"]),
            tuple(SplitGroup.from_dict(group) for group in value["groups"]),
        )


@dataclass
class SplitResult:
    source_study_instance_uid: str
    group_study_instance_uids: dict[str, str] = field(default_factory=dict)
    series_instance_uid_map: dict[str, dict[str, str]] = field(default_factory=dict)
    sop_instance_uid_map: dict[str, dict[str, str]] = field(default_factory=dict)
    written_files: list[Path] = field(default_factory=list)
    unassigned_series_instance_uids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_study_instance_uid": self.source_study_instance_uid,
            "group_study_instance_uids": self.group_study_instance_uids,
            "series_instance_uid_map": self.series_instance_uid_map,
            "sop_instance_uid_map": self.sop_instance_uid_map,
            "written_files": [str(path) for path in self.written_files],
            "unassigned_series_instance_uids": self.unassigned_series_instance_uids,
        }


class StudySplitService:
    """Create one or more newly UIDed studies from selected source series."""

    def __init__(self, uid_factory: Callable[[], str] = generate_uid) -> None:
        self._uid_factory = uid_factory

    def split(
        self,
        manifest: SplitManifest,
        *,
        dry_run: bool = False,
        allow_unassigned: bool = False,
        overwrite: bool = False,
    ) -> SplitResult:
        self._validate_manifest(manifest)
        instances = self._load_instances(manifest.source_folder)
        source_studies = {str(dataset.StudyInstanceUID) for _, dataset in instances}
        if len(source_studies) != 1:
            raise ValueError(
                "Source folder must contain exactly one StudyInstanceUID; "
                f"found {len(source_studies)}."
            )

        source_study_uid = next(iter(source_studies))
        available_series = {str(dataset.SeriesInstanceUID) for _, dataset in instances}
        source_sop_uids = [str(dataset.SOPInstanceUID) for _, dataset in instances]
        if len(source_sop_uids) != len(set(source_sop_uids)):
            raise ValueError("Source folder contains duplicate SOPInstanceUID values.")
        configured_series = set().union(*(group.series_instance_uids for group in manifest.groups))
        unknown = sorted(configured_series - available_series)
        if unknown:
            raise ValueError(f"Configured SeriesInstanceUID values were not found: {', '.join(unknown)}")

        unassigned = sorted(available_series - configured_series)
        if unassigned and not allow_unassigned:
            raise ValueError("Source series are not assigned to a split group: " + ", ".join(unassigned))

        result = SplitResult(source_study_uid, unassigned_series_instance_uids=unassigned)
        for group in manifest.groups:
            selected = [item for item in instances if str(item[1].SeriesInstanceUID) in group.series_instance_uids]
            study_uid = self._new_uid()
            series_map = {uid: self._new_uid() for uid in sorted(group.series_instance_uids)}
            sop_map = {str(dataset.SOPInstanceUID): self._new_uid() for _, dataset in selected}
            uid_map = {source_study_uid: study_uid, **series_map, **sop_map}

            result.group_study_instance_uids[group.name] = study_uid
            result.series_instance_uid_map[group.name] = series_map
            result.sop_instance_uid_map[group.name] = sop_map

            for source_path, source_dataset in selected:
                dataset = deepcopy(source_dataset)
                self._replace_uid_references(dataset, uid_map)
                if group.accession_number is not None:
                    dataset.AccessionNumber = group.accession_number
                if group.study_description is not None:
                    dataset.StudyDescription = group.study_description

                output_path = manifest.output_folder / group.name / source_path.relative_to(manifest.source_folder)
                if output_path.exists() and not overwrite:
                    raise FileExistsError(f"Output already exists: {output_path}")
                result.written_files.append(output_path)
                if not dry_run:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    dataset.save_as(output_path, enforce_file_format=True)

        return result

    @staticmethod
    def _validate_manifest(manifest: SplitManifest) -> None:
        if not manifest.source_folder.is_dir():
            raise FileNotFoundError(f"Source folder not found: {manifest.source_folder}")
        if not manifest.groups:
            raise ValueError("At least one split group is required.")

        names = [group.name for group in manifest.groups]
        if any(not name or Path(name).name != name for name in names):
            raise ValueError("Group names must be non-empty directory names.")
        if len(set(names)) != len(names):
            raise ValueError("Split group names must be unique.")

        seen: set[str] = set()
        for group in manifest.groups:
            if not group.series_instance_uids:
                raise ValueError(f"Split group '{group.name}' has no series.")
            duplicate = seen.intersection(group.series_instance_uids)
            if duplicate:
                raise ValueError("A source series may belong to only one split group: " + ", ".join(sorted(duplicate)))
            seen.update(group.series_instance_uids)

        source = manifest.source_folder.resolve()
        output = manifest.output_folder.resolve()
        if output == source or source in output.parents:
            raise ValueError("Output folder cannot be the source folder or a child of it.")

    @staticmethod
    def _load_instances(source_folder: Path) -> list[tuple[Path, Dataset]]:
        instances: list[tuple[Path, Dataset]] = []
        for path in sorted(candidate for candidate in source_folder.rglob("*") if candidate.is_file()):
            try:
                dataset = pydicom.dcmread(path)
            except Exception:  # Non-DICOM files are intentionally ignored.
                continue
            required = ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID")
            missing = [keyword for keyword in required if not getattr(dataset, keyword, None)]
            if missing:
                raise ValueError(f"DICOM file {path} is missing: {', '.join(missing)}")
            instances.append((path, dataset))
        if not instances:
            raise ValueError(f"No readable DICOM instances found in: {source_folder}")
        return instances

    @staticmethod
    def _replace_uid_references(dataset: Dataset, uid_map: dict[str, str]) -> None:
        for element in dataset.iterall():
            if element.VR != "UI":
                continue
            if isinstance(element.value, (list, MultiValue)):
                element.value = [uid_map.get(str(value), value) for value in element.value]
            else:
                element.value = uid_map.get(str(element.value), element.value)

        sop_uid = str(dataset.SOPInstanceUID)
        if getattr(dataset, "file_meta", None) is None:
            dataset.file_meta = Dataset()
        dataset.file_meta.MediaStorageSOPInstanceUID = sop_uid

    def _new_uid(self) -> str:
        uid = str(self._uid_factory())
        if not UID(uid).is_valid:
            raise ValueError(f"UID factory produced an invalid DICOM UID: {uid}")
        return uid


def _resolve_from(base: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None
