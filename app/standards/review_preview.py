"""Source-page preview for the expert tool, independent of the drawing viewer."""
from hashlib import sha256
import tkinter as tk
from tkinter import ttk

import pymupdf
from PIL import ImageTk

from app.pdf_reader import pixmap_to_image


class SourcePreview(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.source_bytes = None
        self.page = 1
        self.page_count = 0
        self.scale = 0.75
        self.message = tk.StringVar(value="Выберите пункт")
        ttk.Label(self, textvariable=self.message, wraplength=460).pack(fill="x", pady=4)
        controls = ttk.Frame(self)
        controls.pack(fill="x")
        ttk.Button(controls, text="←", command=lambda: self.show_page(self.page - 1)).pack(side="left")
        ttk.Button(controls, text="→", command=lambda: self.show_page(self.page + 1)).pack(side="left")
        ttk.Button(controls, text="−", command=lambda: self.zoom(1 / 1.2)).pack(side="left")
        ttk.Button(controls, text="+", command=lambda: self.zoom(1.2)).pack(side="left")
        ttk.Label(self, text="Точных bbox нет: показана страница без подсветки.", wraplength=460).pack(fill="x")
        area = ttk.Frame(self)
        area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(area, background="#777777", highlightthickness=0)
        vertical = ttk.Scrollbar(area, command=self.canvas.yview)
        horizontal = ttk.Scrollbar(area, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.bind("<ButtonPress-1>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B1-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))

    def clear(self, message):
        self.source_bytes = None
        self.canvas.delete("source_image")
        self.canvas.image = None
        self.message.set(message)

    def load_source(self, path, expected_sha256, page=1):
        self.clear("Исходный PDF недоступен локально (не найден файл с нужным SHA-256).")
        if path is None:
            return
        try:
            raw = path.read_bytes()
            if sha256(raw).hexdigest() != expected_sha256:
                self.message.set("Исходный PDF изменился: SHA-256 не совпадает.")
                return
            with pymupdf.open(stream=raw, filetype="pdf") as pdf:
                self.page_count = len(pdf)
            self.source_bytes = raw
            self.scale = 0.75
            self.show_page(page)
        except Exception as exc:
            self.clear(f"Исходный PDF недоступен локально: {exc}")

    def show_page(self, page):
        if self.source_bytes is None:
            return
        if not 1 <= page <= self.page_count:
            self.message.set(f"Допустимые страницы: 1–{self.page_count}")
            return
        try:
            with pymupdf.open(stream=self.source_bytes, filetype="pdf") as pdf:
                pixmap = pdf[page - 1].get_pixmap(matrix=pymupdf.Matrix(self.scale, self.scale),
                                                colorspace=pymupdf.csRGB, alpha=False)
            photo = ImageTk.PhotoImage(pixmap_to_image(pixmap), master=self.canvas)
            self.canvas.delete("source_image")
            self.canvas.create_image(0, 0, image=photo, anchor="nw", tags=("source_image",))
            self.canvas.image = photo
            self.canvas.configure(scrollregion=(0, 0, pixmap.width, pixmap.height))
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)
            self.page = page
            self.message.set(f"Страница {page} из {self.page_count}")
        except Exception as exc:
            self.message.set(f"Не удалось показать страницу: {exc}")

    def zoom(self, factor):
        self.scale = max(0.2, min(3.0, self.scale * factor))
        self.show_page(self.page)
