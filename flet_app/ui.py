"""Main UI builder for Flet file search app."""

import csv
import os
import subprocess
import sys
from threading import Thread
import flet as ft
from searcher import FileSearcher
from validator import find_duplicates, format_size


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
            ft.DataColumn(ft.Text("Advarsler")),
            ft.DataColumn(ft.Text("Sti")),
        ],
        expand=True,
        sort_column_index=0,
        sort_ascending=True,
    )
    results_scroll = ft.ListView(expand=True)
    results_scroll.controls.append(results_table)

    # Quality report tab
    report_text = ft.Markdown("", expand=True, selectable=True)
    report_scroll = ft.ListView(expand=True)
    report_scroll.controls.append(report_text)

    # Tabs
    tabs = ft.Tabs(
        selected_index=0,
        tabs=[
            ft.Tab(text="Resultater", content=results_scroll),
            ft.Tab(text="Kvalitetsrapport", content=report_scroll),
        ],
        expand=True,
    )

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
    dup_btn = ft.ElevatedButton("Find dubletter", disabled=True)

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
        warnings = info.get("warnings", [])
        warn_text = "; ".join(warnings) if warnings else ""
        row_color = ft.Colors.AMBER_50 if warnings else None

        results_table.rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(info["name"])),
                    ft.DataCell(ft.Text(info["ext"])),
                    ft.DataCell(ft.Text(format_size(info["size"]))),
                    ft.DataCell(ft.Text(info["modified"])),
                    ft.DataCell(ft.Text(warn_text, color=ft.Colors.ORANGE_800 if warnings else None, size=11)),
                    ft.DataCell(ft.Text(info["path"], size=11)),
                ],
                color=row_color,
                on_select_changed=lambda e, p=info["path"]: open_file_location(p)(e),
            )
        )
        page.update()

    def generate_report():
        data = results_data
        total = len(data)
        total_size = sum(r["size"] for r in data)

        lines = [
            f"## Kvalitetsrapport\n",
            f"**Samlet:** {total} filer, {format_size(total_size)}\n",
            "### Filtyper\n",
        ]

        ext_counts = {}
        for r in data:
            ext = r["ext"] or "(ingen)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
        for ext, cnt in sorted(ext_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- **{ext}**: {cnt} filer")

        warn_files = [r for r in data if r.get("warnings")]
        if warn_files:
            lines.append(f"\n### Advarsler ({len(warn_files)} filer)\n")
            warn_types = {}
            for r in warn_files:
                for w in r["warnings"]:
                    warn_types.setdefault(w, []).append(r)
            for wtype, files in sorted(warn_types.items(), key=lambda x: -len(x[1])):
                lines.append(f"\n**{wtype}** ({len(files)})\n")
                for f in files[:20]:
                    lines.append(f"- {f['name']} *– {f['path']}*")
                if len(files) > 20:
                    lines.append(f"- *...og {len(files) - 20} flere*")
        else:
            lines.append("\n### Ingen advarsler fundet")

        report_text.value = "\n".join(lines)

    def on_done(count: int):
        search_btn.disabled = False
        export_btn.disabled = count == 0
        dup_btn.disabled = count == 0

        total_size = sum(r["size"] for r in results_data)
        warn_count = sum(1 for r in results_data if r.get("warnings"))
        status_text.value = (
            f"Fandt {count} fil(er) – {format_size(total_size)} – {warn_count} med advarsler"
        )

        generate_report()
        page.update()

    def start_search(e):
        directory = (dir_input.value or "").strip()
        if not directory:
            return

        if searcher_ref["current"]:
            searcher_ref["current"].stop()

        results_table.rows.clear()
        results_data.clear()
        report_text.value = ""
        search_btn.disabled = True
        export_btn.disabled = True
        dup_btn.disabled = True
        status_text.value = "Søger..."
        page.update()

        query = (search_input.value or "").strip()
        extensions = parse_extensions()

        searcher = FileSearcher(directory, query, add_result, on_done, recursive_cb.value, extensions)
        searcher_ref["current"] = searcher
        searcher.start()

    def run_duplicate_check(e):
        dup_btn.disabled = True
        status_text.value = "Søger efter dubletter (beregner hash)..."
        page.update()

        def do_check():
            duplicates = find_duplicates(results_data)

            # Mark duplicate rows
            dup_paths = set()
            for group in duplicates.values():
                for f in group:
                    dup_paths.add(f["path"])

            for row in results_table.rows:
                path_cell = row.cells[5].content
                if hasattr(path_cell, "value") and path_cell.value in dup_paths:
                    row.color = ft.Colors.RED_50

            # Add to report
            lines = [report_text.value, "\n### Dubletter\n"]
            if duplicates:
                total_dup = sum(len(g) for g in duplicates.values())
                wasted = sum(
                    sum(f["size"] for f in group[1:])
                    for group in duplicates.values()
                )
                lines.append(
                    f"**{total_dup} filer** i **{len(duplicates)} grupper** "
                    f"– spildplads: **{format_size(wasted)}**\n"
                )
                for i, (h, group) in enumerate(duplicates.items(), 1):
                    lines.append(f"\n**Gruppe {i}** ({len(group)} filer, {format_size(group[0]['size'])} hver)\n")
                    for f in group:
                        lines.append(f"- {f['path']}")
            else:
                lines.append("Ingen dubletter fundet.")

            report_text.value = "\n".join(lines)
            dup_btn.disabled = False
            tabs.selected_index = 1

            dup_count = sum(len(g) for g in duplicates.values()) if duplicates else 0
            status_text.value = f"Dublet-tjek færdig – {dup_count} dubletter i {len(duplicates)} grupper"
            page.update()

        Thread(target=do_check, daemon=True).start()

    def export_csv_action(e):
        def on_save_result(e: ft.FilePickerResultEvent):
            if not e.path:
                return
            path = e.path
            if not path.endswith(".csv"):
                path += ".csv"
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Filnavn", "Type", "Størrelse (bytes)", "Ændret", "Advarsler", "Fuld sti"])
                for info in results_data:
                    warnings = "; ".join(info.get("warnings", []))
                    writer.writerow([info["name"], info["ext"], info["size"], info["modified"], warnings, info["path"]])
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
    dup_btn.on_click = run_duplicate_check

    browse_btn = ft.ElevatedButton("Gennemse...", on_click=pick_directory)

    page.add(
        ft.Row([dir_input, browse_btn]),
        ft.Row([search_input, recursive_cb, search_btn]),
        ft.Row([ext_input] + ext_buttons),
        ft.Divider(),
        tabs,
        ft.Divider(),
        ft.Row([export_btn, dup_btn, ft.Container(expand=True), status_text]),
    )
