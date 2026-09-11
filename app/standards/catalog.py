"""A validated snapshot: construction either succeeds in full or raises."""
from copy import deepcopy
from pathlib import Path

from app.standards.errors import NormativeLookupError, NormativeValidationError
from app.standards.loader import load_clause, load_document, load_rule
from app.standards.models import RuleDefinition, RuleStatus, StandardClause, StandardDocument, StandardStatus


def _index(entities, model):
    result = {}
    for entity in entities:
        if not isinstance(entity, model):
            raise NormativeValidationError(f"expected {model.__name__}")
        entity = deepcopy(entity)
        entity.__post_init__()
        if entity.id in result:
            raise NormativeValidationError(f"duplicate {model.__name__} id: {entity.id}")
        result[entity.id] = entity
    return result


class NormativeRegistry:
    """One rule version per id. Document/clause ids identify a specific edition.

    clauses=None means not loaded; clauses=[] means loaded and empty.
    All exposed entities are copies, protecting validated references and parameters.
    """

    def __init__(self, documents=(), clauses=None, rules=()):
        self._documents = _index(documents, StandardDocument)
        self._clauses_loaded = clauses is not None
        self._clauses = _index(clauses if clauses is not None else (), StandardClause)
        self._rules = _index(rules, RuleDefinition)
        for clause in self._clauses.values():
            if clause.document_id not in self._documents:
                raise NormativeValidationError(
                    f"clause {clause.id}: unknown document_id {clause.document_id}")
            provenance = self._documents[clause.document_id].provenance
            last_page = clause.page_end if clause.page_end is not None else clause.page
            if provenance is not None and last_page is not None and last_page > provenance.page_count:
                raise NormativeValidationError(f"clause {clause.id}: page exceeds source page_count")
        for rule in self._rules.values():
            self.validate_rule(rule)

    @property
    def clauses_loaded(self):
        return self._clauses_loaded

    def validate_rule(self, rule):
        rule.__post_init__()
        document = self._documents.get(rule.standard_document_id)
        if document is None:
            raise NormativeValidationError(
                f"rule {rule.id}: unknown document_id {rule.standard_document_id}")
        if rule.status == RuleStatus.ACTIVE and document.status != StandardStatus.ACTIVE:
            raise NormativeValidationError(
                f"rule {rule.id}: active rule requires active document; "
                f"{document.id} is {document.status.value}")
        if self.clauses_loaded:
            for clause_id in rule.clause_ids:
                clause = self._clauses.get(clause_id)
                if clause is None:
                    raise NormativeValidationError(f"rule {rule.id}: unknown clause {clause_id}")
                if clause.document_id != document.id:
                    raise NormativeValidationError(
                        f"rule {rule.id}: clause {clause_id} belongs to another document")

    @staticmethod
    def _get(index, entity_id, kind):
        try:
            return deepcopy(index[entity_id])
        except KeyError:
            raise NormativeLookupError(f"unknown {kind} id: {entity_id}") from None

    def get_document(self, document_id):
        return self._get(self._documents, document_id, "document")

    def get_clause(self, clause_id):
        return self._get(self._clauses, clause_id, "clause")

    def get_rule(self, rule_id):
        return self._get(self._rules, rule_id, "rule")

    def find_rules(self, *, category=None, status=None):
        if status is not None:
            try:
                status = RuleStatus(status)
            except (ValueError, TypeError):
                raise NormativeValidationError(f"unknown rule status: {status}") from None
        return tuple(deepcopy(rule) for rule in self._rules.values()
                     if (category is None or rule.category == category)
                     and (status is None or rule.status == status))

    def active_rules(self):
        return self.find_rules(status=RuleStatus.ACTIVE)

    @classmethod
    def from_files(cls, *, document_files, rule_files=(), clause_files=None):
        """Load everything before publishing the registry; paths appear in errors."""
        origins = []

        def read(paths, loader):
            entities = []
            for path in paths:
                entity = loader(path)
                entities.append(entity)
                origins.append(f"{entity.id} ({path})")
            return entities

        documents = read(document_files, load_document)
        clauses = None if clause_files is None else read(clause_files, load_clause)
        rules = read(rule_files, load_rule)
        try:
            return cls(documents, clauses, rules)
        except NormativeValidationError as exc:
            raise NormativeValidationError(f"{exc}; loaded from: {'; '.join(origins)}") from exc

    @classmethod
    def from_directory(cls, root):
        root = Path(root)

        def files(relative, *, optional=False):
            folder = root / relative
            if optional and not folder.exists():
                return None
            if not folder.is_dir():
                raise NormativeValidationError(f"missing catalog directory: {folder}")
            return sorted(folder.rglob("*.json"))

        return cls.from_files(document_files=files("processed/documents"),
                              clause_files=files("processed/clauses", optional=True),
                              rule_files=files("rules"))
