"""Main UI builder for Flet file search app."""

import os
import subprocess
import sys
import flet as ft
from searcher import FileSearcher


def build_ui(page: ft.Page):
    searcher_ref = {"current": None}

    results = ft.ListView(expand=True, spacing=2)
    status_text = ft.Text("Klar.", size=12)

    dir_input = ft.TextField(
        value=os.path.expanduser("~"),
        label="Mappe",
        expand=True,
    )
    search_input = ft.TextField(
        label="Søg",
        hint_text="Skriv filnavn eller del af filnavn...",
        expand=True,
    )
    search_btn = ft.ElevatedButton("Søg")

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

    def add_result(path: str):
        results.controls.append(
            ft.TextButton(
                path,
                on_click=open_file_location(path),
                style=ft.ButtonStyle(padding=5),
            )
        )
        page.update()

    def on_done(count: int):
        search_btn.disabled = False
        status_text.value = f"Fandt {count} fil(er)."
        page.update()

    def start_search(e):
        query = search_input.value.strip() if search_input.value else ""
        directory = dir_input.value.strip() if dir_input.value else ""
        if not query or not directory:
            return

        if searcher_ref["current"]:
            searcher_ref["current"].stop()

        results.controls.clear()
        search_btn.disabled = True
        status_text.value = "Søger..."
        page.update()

        searcher = FileSearcher(directory, query, add_result, on_done)
        searcher_ref["current"] = searcher
        searcher.start()

    search_btn.on_click = start_search
    search_input.on_submit = start_search

    browse_btn = ft.ElevatedButton("Gennemse...", on_click=pick_directory)

    page.add(
        ft.Row([dir_input, browse_btn]),
        ft.Row([search_input, search_btn]),
        ft.Divider(),
        results,
        ft.Divider(),
        status_text,
    )
