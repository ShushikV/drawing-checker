"""Internal human-review tool. The drawing viewer and analysis UI are unchanged."""
import argparse
import json
from dataclasses import asdict
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from app.standards.review_preview import SourcePreview
from app.standards.verification_models import ReviewStatus
from app.standards.verification_service import VerificationService


class ReviewWindow(tk.Toplevel):
    def __init__(self, master, service: VerificationService):
        super().__init__(master)
        self.service = service
        self.title("Drawing Checker — верификация нормативных пунктов")
        self.geometry("1480x920")
        self.state_data = None
        self.document_id = None
        self.documents_by_id = {}
        self.message = tk.StringVar(value="Выберите документ и пункт")
        self.current_status = tk.StringVar(value="—")
        self.filter_status = tk.StringVar(value="all")
        self.operator = tk.StringVar()
        self.fields = {name: tk.StringVar() for name in ("clause_number", "title", "page_start", "page_end")}
        self.clause_id_text = tk.StringVar()
        self._initial_form = None
        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, width=270)
        center = ttk.Frame(panes)
        right = ttk.Frame(panes, width=490)
        panes.add(left, weight=1)
        panes.add(center, weight=3)
        panes.add(right, weight=2)
        ttk.Label(left, text="Документы").pack(anchor="w")
        self.document_list = ttk.Treeview(left, show="tree", selectmode="browse", height=7)
        self.document_list.pack(fill="both", expand=True)
        self.document_list.bind("<<TreeviewSelect>>", self._document_selected)
        ttk.Label(left, text="Статус пунктов").pack(anchor="w")
        self.filter = ttk.Combobox(left, textvariable=self.filter_status, state="readonly",
                                   values=("all", *(s.value for s in ReviewStatus)))
        self.filter.pack(fill="x")
        self.filter.bind("<<ComboboxSelected>>", lambda event: self.refresh_clauses())
        self.clause_list = ttk.Treeview(left, columns=("status",), selectmode="browse", height=18)
        self.clause_list.heading("#0", text="Пункт")
        self.clause_list.heading("status", text="Статус")
        self.clause_list.column("#0", width=120)
        self.clause_list.column("status", width=105)
        self.clause_list.pack(fill="both", expand=True)
        self.clause_list.bind("<<TreeviewSelect>>", self._clause_selected)
        ttk.Button(left, text="Обновить списки", command=self.refresh_documents).pack(fill="x")
        self.preview = SourcePreview(center)
        self.preview.pack(fill="both", expand=True)
        ttk.Label(right, textvariable=self.clause_id_text, wraplength=450).pack(fill="x")
        ttk.Label(right, textvariable=self.current_status, font=("Arial", 12, "bold")).pack(anchor="w")
        for name, label in (("clause_number", "Номер пункта"), ("title", "Заголовок")):
            ttk.Label(right, text=label).pack(anchor="w")
            ttk.Entry(right, textvariable=self.fields[name]).pack(fill="x")
        page_fields = ttk.Frame(right)
        page_fields.pack(fill="x", pady=4)
        for name, label in (("page_start", "Начало"), ("page_end", "Конец")):
            ttk.Label(page_fields, text=label).pack(side="left")
            ttk.Entry(page_fields, textvariable=self.fields[name], width=5).pack(side="left")
            ttk.Button(page_fields, text="Показать", command=lambda key=name: self.goto_page(key)).pack(side="left")
        tabs = ttk.Notebook(right)
        tabs.pack(fill="both", expand=True)
        self.raw_text = self._tab_text(tabs, "Raw импорт", editable=False)
        self.normalized_text = self._tab_text(tabs, "Normalized импорт", editable=False)
        self.verified_text = self._tab_text(tabs, "Текст решения", editable=True)
        self.diagnostics_text = self._tab_text(tabs, "Diagnostics / provenance", editable=False)
        tabs.select(2)
        ttk.Label(right, text="Примечание").pack(anchor="w")
        self.note_text = tk.Text(right, height=3, wrap="word")
        self.note_text.pack(fill="x")
        ttk.Label(right, text="Проверяющий (verified_by / reviewed_by)").pack(anchor="w")
        ttk.Entry(right, textvariable=self.operator).pack(fill="x")
        self.buttons = {}
        for action, label in (("verify", "Подтвердить"), ("review", "Нужно проверить"),
                              ("reject", "Отклонить"), ("save", "Сохранить исправления")):
            button = ttk.Button(right, text=label, command=lambda key=action: self.save_action(key), state="disabled")
            button.pack(fill="x", pady=2)
            self.buttons[action] = button
        ttk.Button(right, text="История ревизий", command=self.show_history).pack(fill="x")
        ttk.Label(self, textvariable=self.message, wraplength=1400).pack(fill="x", padx=8, pady=6)
        self.refresh_documents()

    @staticmethod
    def _tab_text(tabs, title, editable):
        frame = ttk.Frame(tabs)
        text = tk.Text(frame, wrap="word", width=48, height=18, state="normal" if editable else "disabled")
        scroll = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        tabs.add(frame, text=title)
        return text

    @staticmethod
    def _put(widget, text, readonly=False):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        if readonly:
            widget.configure(state="disabled")

    def _form(self):
        return {**{key: value.get() for key, value in self.fields.items()},
                "verified_text": self.verified_text.get("1.0", "end-1c"),
                "note": self.note_text.get("1.0", "end-1c")}

    def _dirty(self):
        return self._initial_form is not None and self._form() != self._initial_form

    def refresh_documents(self):
        if self._dirty():
            self.message.set("Есть несохранённые изменения. Сохраните исправления перед обновлением.")
            return
        try:
            documents = self.service.documents()
            self.documents_by_id = {d.id: d for d in documents}
            self.document_list.delete(*self.document_list.get_children())
            for document in documents:
                self.document_list.insert("", "end", iid=document.id, text=f"{document.designation} · {document.version}")
            if documents:
                document_id = self.document_id if self.document_id in self.documents_by_id else documents[0].id
                self.document_list.selection_set(document_id)
                self.document_id = document_id
                self.refresh_clauses()
            else:
                self.message.set("Импортированных документов пока нет.")
        except (ValueError, OSError) as exc:
            self.message.set(str(exc))

    def _document_selected(self, event=None):
        selected = self.document_list.selection()
        if not selected or selected[0] == self.document_id:
            return
        if self._dirty():
            self.document_list.selection_set(self.document_id)
            self.message.set("Сохраните исправления перед сменой документа.")
            return
        self.document_id = selected[0]
        self.refresh_clauses()

    def refresh_clauses(self):
        if self.document_id is None:
            return
        if self._dirty():
            self.message.set("Сохраните исправления перед сменой фильтра.")
            return
        try:
            status = self.filter_status.get()
            states = self.service.list_clauses(self.document_id, status=None if status == "all" else status)
            old_id = self.state_data.candidate.id if self.state_data else None
            self.clause_list.delete(*self.clause_list.get_children())
            self.state_data = None
            self._initial_form = None
            for state in states:
                self.clause_list.insert("", "end", iid=state.candidate.id,
                    text=state.revision.clause_number if state.revision else state.candidate.clause_number,
                    values=(state.status.value,))
            for button in self.buttons.values():
                button.configure(state="disabled")
            if states:
                ids = {state.candidate.id for state in states}
                chosen = old_id if old_id in ids else states[0].candidate.id
                self.clause_list.selection_set(chosen)
                self.select_clause(chosen)
            else:
                self.current_status.set("Нет пунктов по выбранному фильтру")
                self.clause_id_text.set("")
                for widget in (self.raw_text, self.normalized_text, self.diagnostics_text):
                    self._put(widget, "", readonly=True)
                self._put(self.verified_text, "")
                self.preview.clear("Нет выбранного пункта")
        except (ValueError, OSError) as exc:
            self.message.set(str(exc))

    def _clause_selected(self, event=None):
        selected = self.clause_list.selection()
        if selected and (self.state_data is None or selected[0] != self.state_data.candidate.id):
            self.select_clause(selected[0])

    def select_clause(self, clause_id):
        if self._dirty():
            self.clause_list.selection_set(self.state_data.candidate.id)
            self.message.set("Сохраните исправления перед сменой пункта.")
            return
        try:
            state = self.service.get_state(clause_id)
            self.state_data = state
            candidate, revision = state.candidate, state.revision
            self.clause_id_text.set(candidate.id)
            self.current_status.set(state.status.value + (f" · ревизия {revision.revision}" if revision else ""))
            self.fields["clause_number"].set(revision.clause_number if revision else candidate.clause_number)
            self.fields["title"].set((revision.title if revision else candidate.title) or "")
            self.fields["page_start"].set(revision.page_start if revision else candidate.page)
            self.fields["page_end"].set(revision.page_end if revision else candidate.page_end or candidate.page)
            self._put(self.raw_text, candidate.source_text, readonly=True)
            self._put(self.normalized_text, candidate.normalized_text or candidate.source_text, readonly=True)
            self._put(self.verified_text, revision.verified_text if revision else candidate.normalized_text or candidate.source_text)
            self._put(self.note_text, revision.verification_note if revision else "")
            if revision and not self.operator.get():
                self.operator.set(revision.reviewed_by)
            document = self.service.get_document(candidate.document_id)
            details = {"diagnostics": state.diagnostics, "current_import_fingerprint": state.import_fingerprint,
                "source_spans": [asdict(span) for span in candidate.source_spans],
                "provenance": asdict(document.provenance) if document.provenance else None,
                "last_decision": asdict(revision) if revision else None}
            self._put(self.diagnostics_text, json.dumps(details, ensure_ascii=False, indent=2), readonly=True)
            path = self.service.find_source_pdf(candidate.document_id)
            self.preview.load_source(path, document.provenance.sha256 if document.provenance else "", candidate.page or 1)
            for button in self.buttons.values():
                button.configure(state="normal" if state.current else "disabled")
            self._initial_form = self._form()
            self.message.set("STALE: прежнее решение устарело; проверьте текущий импорт перед подтверждением."
                             if state.status == ReviewStatus.STALE else "Сохранение исправлений не подтверждает пункт: статус будет needs_review.")
        except (ValueError, OSError) as exc:
            self.message.set(str(exc))

    def goto_page(self, key):
        try:
            self.preview.show_page(int(self.fields[key].get()))
        except ValueError:
            self.message.set("Номер страницы должен быть целым числом.")

    def save_action(self, action):
        if self.state_data is None:
            return
        try:
            state = self.state_data
            form = self._form()
            note = form.pop("note")
            form["title"] = form["title"] or None
            form["page_start"] = int(form["page_start"])
            form["page_end"] = int(form["page_end"])
            kwargs = dict(changes=form, note=note,
                          expected_revision=state.revision.revision if state.revision else 0,
                          expected_import_fingerprint=state.import_fingerprint)
            if action == "verify":
                self.service.verify(state.candidate.id, verified_by=self.operator.get(), **kwargs)
            else:
                method = {"save": self.service.save_corrections, "review": self.service.mark_needs_review,
                          "reject": self.service.reject}[action]
                method(state.candidate.id, reviewed_by=self.operator.get(), **kwargs)
            self._initial_form = None
            self.refresh_clauses()
            self.message.set("Решение сохранено. Исходные imported-данные не изменены.")
        except (ValueError, OSError) as exc:
            self.message.set(f"Не сохранено: {exc}")

    def show_history(self):
        if self.state_data is None:
            return
        try:
            clause_id = self.state_data.candidate.id
            history = self.service.history(clause_id)
            data = [{"decision": asdict(r), "original_candidate": asdict(self.service.revision_source(clause_id, r.revision))}
                    for r in history]
            window = tk.Toplevel(self)
            window.title("История — решения и исходные кандидаты")
            text = tk.Text(window, wrap="word", width=100, height=35)
            text.pack(fill="both", expand=True)
            self._put(text, json.dumps(data, ensure_ascii=False, indent=2), readonly=True)
        except (ValueError, OSError) as exc:
            self.message.set(str(exc))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Internal manual verification of imported standard clauses")
    parser.add_argument("--standards-root", type=Path, default=Path("standards"))
    args = parser.parse_args(argv)
    root = tk.Tk()
    root.withdraw()
    window = ReviewWindow(root, VerificationService(args.standards_root))
    window.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
