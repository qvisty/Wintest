"""Main UI builder for Flet file search app."""

import csv
import os
import subprocess
import sys
import flet as ft
from searcher import FileSearcher


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def build_ui(page: ft.Page):
    searcher_ref = {"current": None}
    results_data = []

    # Results table
    results_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Filnavn")),
            ft.DataColumn(ft.Text("Type")),
            ft.DataColumn(ft.Text("Størrelse"), numeric=True),
            ft.DataColumn(ft.Text("Ændret")),
            ft.DataColumn(ft.Text("Sti")),
        ],
        expand=True,
        sort_column_index=0,
        sort_ascending=True,
    )
    results_scroll = ft.ListView(expand=True)
    results_scroll.controls.append(results_table)

    status_text = ft.Text("Klar.", size=12)

    dir_input = ft.TextField(
        value=os.path.expanduser("~"),
        label="Mappe",
        expand=True,
    )
    search_input = ft.TextField(
        label="Søg",
        hint_text="Filnavn eller del af filnavn (tom = alle filer)",
        expand=True,
    )
    ext_input = ft.TextField(
        label="Filtyper",
        hint_text="f.eks. pdf,docx,xlsx (tom = alle)",
        expand=True,
    )
    recursive_cb = ft.Checkbox(label="Inkl. undermapper", value=True)
    search_btn = ft.ElevatedButton("Søg")
    export_btn = ft.ElevatedButton("Eksportér til CSV...", disabled=True)

    # Quick-select extension toggle buttons
    ext_toggles = {}

    def make_ext_toggler(ext):
        def handler(e):
            current = [x.strip() for x in (ext_input.value or "").split(",") if x.strip()]
            if ext in current:
                current.remove(ext)
            else:
                current.append(ext)
            ext_input.value = ",".join(current)
            page.update()
        return handler

    ext_buttons = []
    for ext in ["pdf", "docx", "xlsx", "msg"]:
        btn = ft.OutlinedButton(f".{ext}", on_click=make_ext_toggler(ext))
        ext_buttons.append(btn)

    def parse_extensions():
        text = (ext_input.value or "").strip()
        if not text:
            return None
        return [e.strip().lower().lstrip(".") for e in text.split(",") if e.strip()]

    def pick_directory(e):
        def on_result(e: ft.FilePickerResultEvent):
            if e.path:
                dir_input.value = e.path
                page.update()

        picker = ft.FilePicker(on_result=on_result)
        page.overlay.append(picker)
        page.update()
        picker.get_directory_path(dialog_title="Vælg mappe", initial_directory=dir_input.value)

    def open_file_location(path: str):
        def handler(e):
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        return handler

    def add_result(info: dict):
        results_data.append(info)
        results_table.rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(info["name"])),
                    ft.DataCell(ft.Text(info["ext"])),
                    ft.DataCell(ft.Text(format_size(info["size"]))),
                    ft.DataCell(ft.Text(info["modified"])),
                    ft.DataCell(ft.Text(info["path"], size=11)),
                ],
                on_select_changed=lambda e, p=info["path"]: open_file_location(p)(e),
            )
        )
        page.update()

    def on_done(count: int):
        search_btn.disabled = False
        export_btn.disabled = count == 0
        total_size = sum(r["size"] for r in results_data)
        status_text.value = f"Fandt {count} fil(er) – samlet størrelse: {format_size(total_size)}"
        page.update()

    def start_search(e):
        directory = (dir_input.value or "").strip()
        if not directory:
            return

        if searcher_ref["current"]:
            searcher_ref["current"].stop()

        results_table.rows.clear()
        results_data.clear()
        search_btn.disabled = True
        export_btn.disabled = True
        status_text.value = "Søger..."
        page.update()

        query = (search_input.value or "").strip()
        extensions = parse_extensions()

        searcher = FileSearcher(directory, query, add_result, on_done, recursive_cb.value, extensions)
        searcher_ref["current"] = searcher
        searcher.start()

    def export_csv_action(e):
        def on_save_result(e: ft.FilePickerResultEvent):
            if not e.path:
                return
            path = e.path
            if not path.endswith(".csv"):
                path += ".csv"
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Filnavn", "Type", "Størrelse (bytes)", "Ændret", "Fuld sti"])
                for info in results_data:
                    writer.writerow([info["name"], info["ext"], info["size"], info["modified"], info["path"]])
            status_text.value = f"Eksporteret {len(results_data)} rækker til {path}"
            page.update()

        save_picker = ft.FilePicker(on_result=on_save_result)
        page.overlay.append(save_picker)
        page.update()
        save_picker.save_file(
            dialog_title="Gem CSV-fil",
            file_name="filsøgning.csv",
            allowed_extensions=["csv"],
        )

    search_btn.on_click = start_search
    search_input.on_submit = start_search
    export_btn.on_click = export_csv_action

    browse_btn = ft.ElevatedButton("Gennemse...", on_click=pick_directory)

    page.add(
        ft.Row([dir_input, browse_btn]),
        ft.Row([search_input, recursive_cb, search_btn]),
        ft.Row([ext_input] + ext_buttons),
        ft.Divider(),
        results_scroll,
        ft.Divider(),
        ft.Row([export_btn, ft.Container(expand=True), status_text]),
    )
