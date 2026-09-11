"""python -m app.standards.import_cli --help"""
import argparse
from pathlib import Path
import sys

from app.standards.errors import NormativeValidationError
from app.standards.importer import StandardPdfImporter
from app.standards.import_types import StandardImportError
from app.standards.processed_writer import write_processed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import a normative PDF as draft document/clause candidates. No OCR or rule generation.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--id", required=True, dest="document_id")
    parser.add_argument("--designation", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--version", required=True, help="Document edition, supplied explicitly")
    parser.add_argument("--standards-root", type=Path, default=Path("standards"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--accept-source-change", action="store_true",
                        help="With --overwrite, explicitly accept replacing a different source SHA-256")
    args = parser.parse_args(argv)
    try:
        imported = StandardPdfImporter().import_pdf(args.pdf, document_id=args.document_id,
            designation=args.designation, title=args.title, version=args.version)
        result = write_processed(imported, args.standards_root, overwrite=args.overwrite,
                                 accept_source_change=args.accept_source_change)
    except (StandardImportError, NormativeValidationError, OSError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    print(f"Imported {imported.document.id} (draft; requires human review)")
    print(f"Pages: {len(imported.pages)}; clauses: {len(imported.clauses)}")
    print(f"SHA-256: {imported.document.provenance.sha256}")
    print(f"Warnings: {len(imported.diagnostics) + len(result.warnings)}")
    for diagnostic in imported.diagnostics:
        location = f" page={diagnostic.page} line={diagnostic.line}" if diagnostic.page else ""
        print(f"WARNING [{diagnostic.code}]{location}: {diagnostic.message}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    for path in result.files:
        print(f"Written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
