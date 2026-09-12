"""Read-only verification summaries and integrity checks."""
import argparse
from pathlib import Path
import sys

from app.standards.verification_service import VerificationService


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect human verification decisions; no automatic confirmation.")
    parser.add_argument("--standards-root", type=Path, default=Path("standards"))
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.add_argument("document_id")
    validate = commands.add_parser("validate")
    for command in (status, validate):
        command.add_argument("--standards-root", type=Path, default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    service = VerificationService(args.standards_root)
    try:
        if args.command == "status":
            for name, count in service.status_counts(args.document_id).items():
                print(f"{name}: {count}")
        else:
            service.validate()
            print("Verification storage is valid; no stale decisions.")
    except (ValueError, OSError) as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
