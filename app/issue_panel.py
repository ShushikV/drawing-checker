"""Tk presentation of findings; the domain model remains UI-independent."""
import tkinter as tk
from tkinter import ttk

from app.models import IssueStatus


class IssuePanel(tk.Frame):
    def __init__(self, master, issues, on_select, on_toggle, demo=False, analysis_message=None):
        super().__init__(master, width=360, relief="sunken", borderwidth=1)
        self.pack_propagate(False)
        self.issues = issues
        tk.Label(self, text="Замечания", font=("Arial", 14, "bold")).pack(pady=8)
        tk.Label(self, text="ДЕМО — замечания вымышлены" if demo else
                 "Список переданных замечаний", wraplength=340).pack()
        if analysis_message:
            tk.Label(self, text=analysis_message, wraplength=340, justify="left").pack(fill="x", padx=8, pady=4)
        list_frame = tk.Frame(self)
        list_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree = ttk.Treeview(list_frame, columns=("severity", "status"),
                                 selectmode="browse", height=8)
        self.tree.heading("#0", text="№ / Заголовок")
        self.tree.column("#0", width=175, minwidth=90)
        self.tree.heading("severity", text="Severity")
        self.tree.column("severity", width=65, minwidth=55, stretch=False)
        self.tree.heading("status", text="Статус")
        self.tree.column("status", width=90, minwidth=70, stretch=False)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda event: on_select(
            self.tree.selection()[0]) if self.tree.selection() else None)
        self.details = tk.Text(self, height=12, wrap="word", width=38, state="disabled")
        self.details.pack(fill="both", expand=True, padx=8)
        self.button = tk.Button(self, text="Отметить как выполнено",
                                command=on_toggle, state="disabled")
        self.button.pack(fill="x", padx=8, pady=8)
        self.refresh()
        self.show_details(None, "Выберите замечание." if issues else analysis_message or "Замечаний нет. Проверки не запускались.")

    def refresh(self):
        for number, issue in enumerate(self.issues, 1):
            values = (issue.severity.value,
                      "Выполнено" if issue.status == IssueStatus.DONE else "Открыто")
            if self.tree.exists(issue.id):
                self.tree.item(issue.id, text=f"{number}. {issue.title}", values=values)
            else:
                self.tree.insert("", "end", iid=issue.id,
                                 text=f"{number}. {issue.title}", values=values)

    def show_details(self, issue, notice):
        text = notice
        if issue is not None:
            references = "\n".join(
                " — ".join(part for part in (
                    ref.document, ref.section, ref.url,
                    f"Редакция: {ref.document_version}" if ref.document_version else None,
                    f"Стр. {ref.page}" if ref.page is not None else None, ref.excerpt) if part)
                for ref in issue.requirements)
            text = f"{issue.title}\n\n{issue.description}\n\n{notice}"
            if references:
                text += f"\n\nТребования:\n{references}"
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")
        self.button.configure(state="normal" if issue else "disabled", text=
            "Вернуть ошибку" if issue and issue.status == IssueStatus.DONE
            else "Отметить как выполнено")
