"""Reusable PDF window; PDF rendering remains in pdf_reader."""

import tkinter as tk
from tkinter import messagebox
from PIL import ImageTk
from app.pdf_reader import get_page_geometry, pixmap_to_image, render_page
from app.models import DrawingIssue, IssueStatus
from app.issue_panel import IssuePanel


class PdfViewer(tk.Toplevel):
    """Display the first PDF page with cursor-centered zoom and drag pan."""

    def __init__(self, master, file_path, issues: list[DrawingIssue] | None = None, *, demo=False, analysis_message=None):
        super().__init__(master)
        self.withdraw()
        self.title("Drawing Checker — просмотр чертежа")
        self.geometry("1200x800")
        self.zoom_scale = 1.0
        self.file_path = file_path
        self.issues = list(issues or [])
        self.active_issue_id = None
        self.page_index = 0
        self.demo = demo
        self.analysis_message = analysis_message
        self.protocol("WM_DELETE_WINDOW", self.close)
        try:
            if len({issue.id for issue in self.issues}) != len(self.issues):
                raise ValueError("Issue identifiers must be unique")
            _, _, self.rotation_matrix = get_page_geometry(file_path)
            self._build(file_path)
        except Exception:
            self.destroy()
            raise
        self.deiconify()

    def close(self):
        self.master.deiconify()
        self.destroy()

    def _build(self, file_path):
        file_name_label = tk.Label(
            self,
            text=file_path,
        )
        file_name_label.pack(pady=8)

        content_frame = tk.Frame(self)
        content_frame.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=10,
        )

        canvas = tk.Canvas(
            content_frame,
            background="gray",
            highlightthickness=0,
        )
        self.canvas = canvas
        canvas.pack(
            side="left",
            fill="both",
            expand=True,
        )

        error_panel = IssuePanel(content_frame, self.issues, self.select_issue,
                                 self.toggle_active_issue, demo=self.demo, analysis_message=self.analysis_message)
        self.issue_panel = error_panel
        error_panel.pack(
            side="right",
            fill="y",
            padx=(10, 0),
        )

        canvas.bind(
            "<MouseWheel>",
            self.zoom,
        )

        canvas.bind(
            "<ButtonPress-1>",
            self.start_pan,
        )

        canvas.bind(
            "<B1-Motion>",
            self.pan,
        )

        canvas.bind(
            "<ButtonRelease-1>",
            self.stop_pan,
        )

        self.render_drawing()

    def render_drawing(self):
        canvas = self.canvas
        pixmap = render_page(
            self.file_path,
            zoom=self.zoom_scale,
        )

        image = pixmap_to_image(pixmap)
        photo = ImageTk.PhotoImage(image, master=canvas)

        canvas.delete("pdf_image")

        canvas.create_image(
            0,
            0,
            anchor="nw",
            image=photo,
            tags=("pdf_image",),
        )

        canvas.image = photo

        canvas.configure(
            scrollregion=(
                0,
                0,
                image.width,
                image.height,
            )
        )
        self.draw_overlays()

    def pdf_point_to_canvas(self, x, y):
        """Unrotated PDF points -> rotated, scaled canvas coordinates."""
        a, b, c, d, e, f = self.rotation_matrix
        return ((a * x + c * y + e) * self.zoom_scale,
                (b * x + d * y + f) * self.zoom_scale)

    def pdf_bbox_to_canvas(self, bbox):
        points = [self.pdf_point_to_canvas(x, y)
                  for x in (bbox.x0, bbox.x1) for y in (bbox.y0, bbox.y1)]
        xs, ys = zip(*points)
        return min(xs), min(ys), max(xs), max(ys)

    def draw_overlays(self):
        self.canvas.delete("overlay")
        for number, issue in enumerate(self.issues, 1):
            active = issue.id == self.active_issue_id
            color = "#1769d2" if active else (
                "#28783c" if issue.status == IssueStatus.DONE else "#c0392b")
            for location in issue.locations:
                if location.page_index != self.page_index or location.bbox is None:
                    continue
                box = self.pdf_bbox_to_canvas(location.bbox)
                tags = ("overlay", f"issue:{issue.id}") + (("active",) if active else ())
                self.canvas.create_rectangle(*box, outline=color, width=4 if active else 2,
                    dash=(5, 3) if issue.status == IssueStatus.DONE else (),
                    tags=tags + ("issue_region",))
                x, y = box[:2]
                self.canvas.create_rectangle(x, y, x + 28, y + 22, fill=color,
                    outline=color, tags=tags)
                self.canvas.create_text(x + 14, y + 11, text=str(number), fill="white",
                    font=("Arial", 11, "bold"), tags=tags + ("issue_number",))
        self.canvas.tag_raise("overlay")

    def select_issue(self, issue_id, *, navigate=True):
        issue = next((item for item in self.issues if item.id == issue_id), None)
        if issue is None:
            return
        changed = self.active_issue_id != issue_id
        self.active_issue_id = issue_id
        if self.issue_panel.tree.selection() != (issue_id,):
            self.issue_panel.tree.selection_set(issue_id)
        self.draw_overlays()
        visible = [loc for loc in issue.locations
                   if loc.page_index == self.page_index and loc.bbox is not None]
        other_pages = sorted({loc.page_index + 1 for loc in issue.locations
                              if loc.page_index != self.page_index})
        if visible:
            notice = f"Областей на текущей странице: {len(visible)}. Переход к первой области."
            if navigate and changed:
                self.reveal_bbox(visible[0].bbox)
        elif not issue.locations:
            notice = "Замечание относится ко всему документу, без координат."
        else:
            notice = "На текущей странице нет области для выделения."
        if other_pages:
            notice += ("\nСтраницы: " + ", ".join(map(str, other_pages)) +
                       ". Навигация по страницам ещё не реализована.")
        self.issue_panel.show_details(issue, notice)

    def reveal_bbox(self, bbox):
        self.canvas.update_idletasks()
        x0, y0, x1, y1 = self.pdf_bbox_to_canvas(bbox)
        width, height = self.canvas.image.width(), self.canvas.image.height()
        for start, end, size, viewport, move in (
            (x0, x1, width, self.canvas.winfo_width(), self.canvas.xview_moveto),
            (y0, y1, height, self.canvas.winfo_height(), self.canvas.yview_moveto),
        ):
            offset = ((start + end - viewport) / 2 if end - start < viewport
                      else start - 20)
            move(max(0, min(offset, max(0, size - viewport))) / size)

    def toggle_active_issue(self):
        issue = next((item for item in self.issues if item.id == self.active_issue_id), None)
        if issue is None:
            return
        if issue.status == IssueStatus.DONE:
            issue.reopen()
        else:
            issue.mark_done()
        self.issue_panel.refresh()
        self.select_issue(issue.id, navigate=False)

    def zoom(self, event):
        canvas = self.canvas

        if event.delta == 0:
            return
        old_scale = self.zoom_scale

        if event.delta > 0:
            self.zoom_scale *= 1.2
        else:
            self.zoom_scale /= 1.2

        self.zoom_scale = max(
            0.2,
            min(self.zoom_scale, 5.0),
        )

        if self.zoom_scale == old_scale:
            return

        mouse_x = canvas.canvasx(event.x)
        mouse_y = canvas.canvasy(event.y)

        pdf_x = mouse_x / old_scale
        pdf_y = mouse_y / old_scale

        try:
            self.render_drawing()
        except Exception as exc:
            self.zoom_scale = old_scale
            messagebox.showerror("Ошибка PDF", str(exc), parent=self)
            return

        new_mouse_x = pdf_x * self.zoom_scale
        new_mouse_y = pdf_y * self.zoom_scale

        bbox = canvas.bbox("pdf_image")

        if bbox is None:
            return

        image_width = bbox[2] - bbox[0]
        image_height = bbox[3] - bbox[1]

        if image_width > canvas.winfo_width():
            x_fraction = (
                new_mouse_x - event.x
            ) / image_width

            canvas.xview_moveto(
                max(
                    0.0,
                    min(x_fraction, 1.0),
                )
            )

        if image_height > canvas.winfo_height():
            y_fraction = (
                new_mouse_y - event.y
            ) / image_height

            canvas.yview_moveto(
                max(
                    0.0,
                    min(y_fraction, 1.0),
                )
            )

    def start_pan(self, event):
        canvas = self.canvas
        canvas.scan_mark(
            event.x,
            event.y,
        )

        canvas.configure(
            cursor="fleur",
        )

    def pan(self, event):
        canvas = self.canvas
        canvas.scan_dragto(
            event.x,
            event.y,
            gain=1,
        )

    def stop_pan(self, event):
        canvas = self.canvas
        canvas.configure(
            cursor="",
        )
