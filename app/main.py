

import tkinter as tk
from tkinter import filedialog
from app.pdf_reader import get_page_count, get_page_size

def open_pdf(file_label, page_count_label, page_size_label):
    file_path = filedialog.askopenfilename(
        title="Выберите PDF",
        filetypes=[("PDF files", "*.pdf")],
    )

    print(file_path)

    if file_path:
         file_label.config(text=file_path)

    page_count = get_page_count(file_path)
    page_count_label.config(text=f"Количество страниц: {page_count}")
    width, height = get_page_size(file_path)
    page_size_label.config(
        text=f"Размер страницы: {width:.1f} × {height:.1f} pt"
)

def main():
    root = tk.Tk()
    root.title("Drawing Checker")
    root.geometry("1000x700")
    title_label = tk.Label(
        root,
        text="Drawing Checker",
        font=("Arial", 24),
    )

    title_label.pack(pady=20)
    open_button = tk.Button(
        root,
        text="Открыть PDF",
        command=lambda: open_pdf(
            file_label,
            page_count_label,
            page_size_label,
        ),
    )

    file_label = tk.Label(
        root,
        text="PDF не выбран",
    )

    page_count_label = tk.Label(
        root,
        text="Количество страниц: —",
    )

    page_size_label = tk.Label(
        root,
        text="Размер страницы: —",
    )

    page_size_label.pack(pady=10)

    page_count_label.pack(pady=10)

    file_label.pack(pady=10)

    open_button.pack(pady=10)

    root.mainloop()


if __name__ == "__main__":
    main()