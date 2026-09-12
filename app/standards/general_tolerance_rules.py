"""Source preparation and explicit publication AFTER real human verification.

No production RuleDefinition data is included with the repository.
"""
import argparse
from dataclasses import asdict
from pathlib import Path
import re
import shutil
import sys
import tempfile

from app.analysis.general_tolerances.analyzer import CHECK_TYPE
from app.analysis.general_tolerances.models import ReferenceKind
from app.analysis.general_tolerances.policy import project_parameters, validate_parameters
from app.models import Severity
from app.standards import AutomationLevel, NormativeRegistry, RuleDefinition, RuleStatus
from app.standards.clause_extractor import NumberedClauseExtractor
from app.standards.importer import StandardPdfImporter
from app.standards.processed_writer import _json_bytes, _safe_path, write_processed
from app.standards.verification_service import VerificationService


SOURCES = {
    "gost-30893-1-2002": ("ГОСТ 30893.1-2002.pdf", "ГОСТ 30893.1-2002",
        "Общие допуски. Предельные отклонения линейных и угловых размеров с неуказанными допусками"),
    "gost-30893-2-2002": ("ГОСТ 30893.2-2002.pdf", "ГОСТ 30893.2-2002",
        "Общие допуски. Допуски формы и расположения поверхностей, не указанные индивидуально"),
}
REQUIREMENTS = {
    "size": ("gost-30893-1-2002", "6", (ReferenceKind.SIZE,)),
    "appendix": ("gost-30893-1-2002", "А.4", (ReferenceKind.APPENDIX_1, ReferenceKind.APPENDIX_2)),
    "geometry": ("gost-30893-2-2002", "7.1", (ReferenceKind.GEOMETRY,)),
    "combined": ("gost-30893-2-2002", "7.2", (ReferenceKind.COMBINED,)),
}


class AppendixClauseExtractor(NumberedClauseExtractor):
    """Only extends candidate recognition; it does not verify appendix text."""
    version = "numbered-and-appendix-candidates/1"
    heading = re.compile(r"^([1-9]\d*(?:\.\d+)*|[АA]\.\d+(?:\.\d+)*)[ \t]+(\S.*)$")


def build_rules(catalog, verification, *, parameters=None):
    """Requires the four specified, currently verified sections, without auto-verifying anything."""
    parameters = project_parameters() if parameters is None else parameters
    validate_parameters(parameters)
    definitions = []
    for name, (document_id, clause_number, kinds) in REQUIREMENTS.items():
        document = catalog.get_document(document_id)
        if document.designation != SOURCES[document_id][1] or document.version != "2002":
            raise ValueError(f"{document_id}: требуется указанное обозначение и редакция 2002")
        matching = [state for state in verification.list_clauses(document_id)
                    if state.revision and state.revision.clause_number.replace("A", "А") == clause_number]
        if len(matching) != 1:
            raise ValueError(f"{document_id}: требуется один вручную verified-пункт {clause_number}")
        state = matching[0]
        revision = verification.require_verified(state.candidate.id)
        pins = {revision.clause_id: {"revision": revision.revision,
                                   "import_fingerprint": revision.source_reference.import_fingerprint}}
        rule_parameters = {**parameters, "reference_kinds": [kind.value for kind in kinds]}
        definition = RuleDefinition(f"eskd.general_tolerances.{name}", "Запись общих допусков",
            "Проверка формата присутствующей записи общих допусков по подтверждённому нормативному пункту.",
            "general_tolerances", document_id, (revision.clause_id,), CHECK_TYPE, rule_parameters,
            AutomationLevel.DETERMINISTIC, RuleStatus.ACTIVE, Severity.WARNING, 1,
            {"verified_clause_revisions": pins, "parameter_origin": "stage-6 project specification; review against verified clause"})
        # Use the existing opt-in activation gate, even before definitions are published.
        candidate_catalog = NormativeRegistry([document], [catalog.get_clause(revision.clause_id)], [definition])
        candidate_catalog.validate_rule_activation(definition.id, verification)
        definitions.append(definition)
    return tuple(definitions)


def publish_rules(root):
    root = Path(root).resolve()
    catalog = NormativeRegistry.from_directory(root)
    verification = VerificationService(root)
    definitions = build_rules(catalog, verification)
    target = _safe_path(root, "rules/general_tolerances")
    if target.exists():
        raise ValueError("Каталог general_tolerances уже существует; автоматическая перезапись правил запрещена.")
    existing = {rule.id for rule in catalog.find_rules()}
    if any(rule.id in existing for rule in definitions):
        raise ValueError("Такие rule id уже присутствуют в каталоге.")
    # Stage outside the rules scan, then publish the complete family in one rename.
    stage = Path(tempfile.mkdtemp(prefix=".rule-publication-", dir=root))
    try:
        for rule in definitions:
            (stage / f"{rule.id}.json").write_bytes(_json_bytes(asdict(rule)))
        if build_rules(NormativeRegistry.from_directory(root), verification) != definitions:
            raise ValueError("Verification изменилась во время подготовки правил")
        stage.rename(target)
    finally:
        if stage.exists() and stage.parent == root:
            shutil.rmtree(stage)
    return definitions


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare local sources / publish general-tolerance rules after human review")
    parser.add_argument("command", choices=("status", "import-sources", "publish-rules"))
    parser.add_argument("--standards-root", type=Path, default=Path("standards"))
    args = parser.parse_args(argv)
    try:
        if args.command == "import-sources":
            for document_id, (filename, designation, title) in SOURCES.items():
                source = args.standards_root / "source" / filename
                if not source.is_file():
                    print(f"Missing local source: {source}")
                    continue
                imported = StandardPdfImporter(clause_extractor=AppendixClauseExtractor()).import_pdf(
                    source, document_id=document_id, title=title, designation=designation, version="2002")
                write_processed(imported, args.standards_root)
                print(f"Imported {document_id}: {len(imported.clauses)} candidates; manual verification required.")
        elif args.command == "publish-rules":
            for rule in publish_rules(args.standards_root):
                print(f"Published: {rule.id}")
        else:
            for document_id, (filename, _, _) in SOURCES.items():
                print(f"{document_id}: source {'present' if (args.standards_root / 'source' / filename).is_file() else 'missing'}")
            catalog = NormativeRegistry.from_directory(args.standards_root)
            build_rules(catalog, VerificationService(args.standards_root))
            print("All four required clauses are verified and eligible for rule publication.")
    except (ValueError, LookupError, OSError) as exc:
        print(f"Not ready: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
