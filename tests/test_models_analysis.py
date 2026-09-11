from pathlib import Path

import pytest

from app.analysis import AnalysisContext, RuleRunner
from app.models import BoundingBox, DrawingIssue, IssueLocation, IssueStatus


def test_issue_lifecycle_and_independent_metadata():
    first = DrawingIssue("test", "Title", "Description")
    second = DrawingIssue("test", "Title", "Description")
    assert first.id != second.id
    first.metadata["value"] = 1
    assert second.metadata == {}
    first.mark_done()
    assert first.status == IssueStatus.DONE
    first.reopen()
    assert first.status == IssueStatus.OPEN


@pytest.mark.parametrize("coords", [(2, 0, 1, 1), (0, 2, 1, 1), (0, 0, float("nan"), 1)])
def test_invalid_bbox(coords):
    with pytest.raises(ValueError):
        BoundingBox(*coords)


def test_location():
    assert IssueLocation(0, BoundingBox(1, 2, 3, 4)).page_index == 0
    with pytest.raises(ValueError):
        IssueLocation(-1)


class StubRule:
    def __init__(self, rule_id):
        self.rule_id = rule_id

    def analyze(self, context):
        yield DrawingIssue(self.rule_id, "Test only", str(context.pdf_path))


def test_runner_empty_and_ordered_results():
    context = AnalysisContext(Path("drawing.pdf"))
    assert RuleRunner().analyze(context) == []
    findings = RuleRunner([StubRule("a"), StubRule("b")]).analyze(context)
    assert [issue.rule_id for issue in findings] == ["a", "b"]
    assert findings[0].description == "drawing.pdf"


def test_runner_rejects_duplicate_rule_ids():
    with pytest.raises(ValueError):
        RuleRunner([StubRule("a"), StubRule("a")])


def test_runner_does_not_hide_failure():
    class BrokenRule:
        rule_id = "broken"

        def analyze(self, context):
            raise RuntimeError("failure")

    with pytest.raises(RuntimeError, match="failure"):
        RuleRunner([BrokenRule()]).analyze(AnalysisContext(Path("drawing.pdf")))
