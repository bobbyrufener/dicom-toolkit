import argparse

def main():
    parser = argparse.ArgumentParser(
        prog="dicom-toolkit",
        description="Cross-platform DICOM Toolkit"
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "clone-study",
        help="Clone a DICOM study with modified metadata"
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "clone-study":
        print("clone-study command scaffold is installed.")
        return 0

if __name__ == "__main__":
    raise SystemExit(main())
