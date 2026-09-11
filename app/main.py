import tkinter as tk
from tkinter import filedialog

from PIL import ImageTk

from app.pdf_reader import pixmap_to_image, render_page


def main():
    root = tk.Tk()
    root.title("Drawing Checker")
    root.geometry("1000x700")

    def open_viewer(file_path):
        root.withdraw()

        viewer = tk.Toplevel(root)
        viewer.title("Drawing Checker — просмотр чертежа")
        viewer.geometry("1200x800")

        zoom_scale = 1.0

        def close_viewer():
            viewer.destroy()
            root.deiconify()

        viewer.protocol("WM_DELETE_WINDOW", close_viewer)

        file_name_label = tk.Label(
            viewer,
            text=file_path,
        )
        file_name_label.pack(pady=8)

        canvas = tk.Canvas(
            viewer,
            background="gray",
            highlightthickness=0,
        )
        canvas.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=10,
        )

        def render_drawing():
            pixmap = render_page(
                file_path,
                zoom=zoom_scale,
            )

            image = pixmap_to_image(pixmap)
            photo = ImageTk.PhotoImage(image)

            canvas.delete("all")

            canvas.create_image(
                0,
                0,
                anchor="nw",
                image=photo,
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

        def zoom(event):
            nonlocal zoom_scale

            old_scale = zoom_scale

            if event.delta > 0:
                zoom_scale *= 1.2
            else:
                zoom_scale /= 1.2

            zoom_scale = max(
                0.2,
                min(zoom_scale, 5.0),
            )

            if zoom_scale == old_scale:
                return

            mouse_x = canvas.canvasx(event.x)
            mouse_y = canvas.canvasy(event.y)

            pdf_x = mouse_x / old_scale
            pdf_y = mouse_y / old_scale

            render_drawing()

            new_mouse_x = pdf_x * zoom_scale
            new_mouse_y = pdf_y * zoom_scale

            bbox = canvas.bbox("all")

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

        def start_pan(event):
            canvas.scan_mark(
                event.x,
                event.y,
            )

            canvas.configure(
                cursor="fleur",
            )

        def pan(event):
            canvas.scan_dragto(
                event.x,
                event.y,
                gain=1,
            )

        def stop_pan(event):
            canvas.configure(
                cursor="",
            )

        canvas.bind(
            "<MouseWheel>",
            zoom,
        )

        canvas.bind(
            "<ButtonPress-1>",
            start_pan,
        )

        canvas.bind(
            "<B1-Motion>",
            pan,
        )

        canvas.bind(
            "<ButtonRelease-1>",
            stop_pan,
        )

        render_drawing()

    def choose_pdf():
        file_path = filedialog.askopenfilename(
            title="Выберите PDF",
            filetypes=[
                ("PDF files", "*.pdf"),
            ],
        )

        if not file_path:
            return

        open_viewer(file_path)

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