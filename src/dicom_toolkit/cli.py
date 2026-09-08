from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dicom_toolkit.modify import SplitManifest, StudySplitService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dicom-toolkit", description="Cross-platform DICOM Toolkit")
    subparsers = parser.add_subparsers(dest="command")
    split = subparsers.add_parser(
        "split-study",
        aliases=["clone-study"],
        help="Split selected series into newly UIDed studies",
    )
    split.add_argument("--manifest", required=True, type=Path, help="Path to split manifest JSON.")
    split.add_argument("--dry-run", action="store_true", help="Validate and report without writing files.")
    split.add_argument("--allow-unassigned", action="store_true", help="Allow source series omitted from all groups.")
    split.add_argument("--overwrite", action="store_true", help="Replace existing output files.")
    split.add_argument("--audit-json", type=Path, help="Optional path for the UID mapping report.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return 0

    try:
        result = StudySplitService().split(
            SplitManifest.from_json(args.manifest),
            dry_run=args.dry_run,
            allow_unassigned=args.allow_unassigned,
            overwrite=args.overwrite,
        )
        rendered = json.dumps(result.to_dict(), indent=2)
        print(rendered)
        if args.audit_json:
            args.audit_json.parent.mkdir(parents=True, exist_ok=True)
            args.audit_json.write_text(rendered + "\n", encoding="utf-8")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
