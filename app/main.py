import tkinter as tk
from tkinter import filedialog, messagebox

from app.viewer import PdfViewer
from app.demo_issues import create_demo_issues
from app.analysis.general_tolerances.runtime import check_drawing


def main():
    root = tk.Tk()
    root.title("Drawing Checker")
    root.geometry("1000x700")

    def choose_pdf():
        file_path = filedialog.askopenfilename(
            title="Выберите PDF",
            filetypes=[
                ("PDF files", "*.pdf"),
            ],
        )

        if not file_path:
            return

        try:
            if demo_mode.get():
                issues, analysis_message = create_demo_issues(file_path), None
            else:
                report = check_drawing(file_path)
                issues, analysis_message = report.issues, report.message
            PdfViewer(root, file_path, issues, demo=demo_mode.get(), analysis_message=analysis_message)
        except Exception as exc:
            messagebox.showerror("Не удалось открыть PDF", str(exc), parent=root)
            return
        root.withdraw()

    title_label = tk.Label(
        root,
        text="Drawing Checker",
        font=("Arial", 24),
    )
    title_label.pack(pady=40)

    description_label = tk.Label(
        root,
        text="Проверка инженерных чертежей",
        font=("Arial", 14),
    )
    description_label.pack(pady=10)

    demo_mode = tk.BooleanVar(value=False)
    tk.Checkbutton(root, text="Демо-замечания (вымышленные, без проверки PDF)",
                   variable=demo_mode).pack(pady=10)

    open_button = tk.Button(
        root,
        text="Открыть PDF",
        command=choose_pdf,
        font=("Arial", 14),
    )
    open_button.pack(pady=30)

    root.mainloop()


if __name__ == "__main__":
    main()
