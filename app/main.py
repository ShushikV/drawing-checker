import tkinter as tk
from tkinter import filedialog, messagebox

from app.viewer import PdfViewer
from app.demo_issues import create_demo_issues


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
            issues = create_demo_issues(file_path) if demo_mode.get() else []
            PdfViewer(root, file_path, issues, demo=demo_mode.get())
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
