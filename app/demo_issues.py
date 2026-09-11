"""Synthetic UI examples, never findings from an actual drawing check."""
from app.models import BoundingBox, DrawingIssue, IssueLocation, RequirementReference, Severity
from app.pdf_reader import get_page_geometry


def create_demo_issues(pdf_path):
    width, height, _ = get_page_geometry(pdf_path)

    def area(x, y, w, h):
        return IssueLocation(0, BoundingBox(x * width, y * height,
                                            (x + w) * width, (y + h) * height))

    return [
        DrawingIssue("demo.single", "Демо: одна область",
                     "Вымышленное замечание для проверки выделения и перехода к области.",
                     (area(.15, .2, .18, .1),),
                     (RequirementReference("Демонстрационное требование (не ГОСТ)", "Пример 1"),)),
        DrawingIssue("demo.multiple", "Демо: две области",
                     "Обе области относятся к одному замечанию. Переход — к первой области.",
                     (area(.6, .3, .15, .1), area(.5, .7, .2, .12)),
                     severity=Severity.WARNING),
        DrawingIssue("demo.document", "Демо: весь документ",
                     "Замечание без координат. Маркер на PDF не создаётся.", severity=Severity.INFO),
        DrawingIssue("demo.other_page", "Демо: другая страница",
                     "Проверка сообщения о недоступной навигации. Страница 2 может отсутствовать в PDF.",
                     (IssueLocation(1, BoundingBox(10, 10, 80, 60)),)),
    ]
