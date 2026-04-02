"""Main UI builder for Flet file search app."""

import csv
import os
import subprocess
import sys
from threading import Thread
import flet as ft
from searcher import FileSearcher
from validator import find_duplicates, format_size
from metadata import extract_metadata
from tagger import TagStore


def build_ui(page: ft.Page):
    searcher_ref = {"current": None}
    results_data = []
    tag_store = TagStore()

    # --- Results table ---
    results_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Filnavn")),
            ft.DataColumn(ft.Text("Type")),
            ft.DataColumn(ft.Text("Størrelse"), numeric=True),
            ft.DataColumn(ft.Text("Ændret")),
            ft.DataColumn(ft.Text("Advarsler")),
            ft.DataColumn(ft.Text("Tags")),
            ft.DataColumn(ft.Text("Sti")),
        ],
        expand=True,
        sort_column_index=0,
        sort_ascending=True,
    )
    results_scroll = ft.ListView(expand=True)
    results_scroll.controls.append(results_table)

    # --- Quality report ---
    report_text = ft.Markdown("", expand=True, selectable=True)
    report_scroll = ft.ListView(expand=True)
    report_scroll.controls.append(report_text)

    # --- Case mappings report ---
    case_report_text = ft.Markdown("", expand=True, selectable=True)
    case_report_scroll = ft.ListView(expand=True)
    case_report_scroll.controls.append(case_report_text)

    # --- Tabs ---
    tabs = ft.Tabs(
        selected_index=0,
        tabs=[
            ft.Tab(text="Resultater", content=results_scroll),
            ft.Tab(text="Kvalitetsrapport", content=report_scroll),
            ft.Tab(text="Sagsnr.-oversigt", content=case_report_scroll),
        ],
        expand=True,
    )

    # --- Detail panel (right side) ---
    preview_image = ft.Image(visible=False, width=260, height=160, fit=ft.ImageFit.CONTAIN)
    preview_text = ft.Text("Vælg en fil for at se detaljer", size=12)
    meta_text = ft.Markdown("", selectable=True)
    tag_display = ft.Text("Ingen tags", size=12)
    tag_combo = ft.TextField(label="Tag", hint_text="Skriv tag...", expand=True, dense=True)

    selected_path_ref = {"current": ""}

    status_text = ft.Text("Klar.", size=12)

    dir_input = ft.TextField(
        value=os.path.expanduser("~"),
        label="Mappe",
        expand=True,
    )
    case_input = ft.TextField(
        label="Sagsnr.",
        hint_text="Tildel sagsnr. til den valgte mappe...",
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

    # --- Case number ---

    def load_case_number():
        directory = (dir_input.value or "").strip()
        case = tag_store.get_case_number(directory) if directory else ""
        case_input.value = case

    def save_case_number(e):
        directory = (dir_input.value or "").strip()
        case = (case_input.value or "").strip()
        if directory:
            tag_store.set_case_number(directory, case)
            status_text.value = f"Sagsnr. '{case}' gemt for {directory}"
            update_case_report()
            page.update()

    def update_case_report():
        mappings = tag_store.get_all_case_mappings()
        if not mappings:
            case_report_text.value = "Ingen sagsnr.-mappinger gemt endnu."
            return
        lines = ["## Sagsnr.-oversigt\n", "| Mappe | Sagsnr. |", "|---|---|"]
        for folder, case in sorted(mappings.items()):
            lines.append(f"| {folder} | **{case}** |")
        case_report_text.value = "\n".join(lines)

    def on_dir_change(e):
        load_case_number()
        page.update()

    dir_input.on_change = on_dir_change

    # --- Extension toggles ---

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

    # --- Directory picker ---

    def pick_directory(e):
        def on_result(e: ft.FilePickerResultEvent):
            if e.path:
                dir_input.value = e.path
                load_case_number()
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

    # --- Selection / Preview / Metadata ---

    def on_row_selected(path):
        def handler(e):
            selected_path_ref["current"] = path
            refresh_detail_panel(path)
        return handler

    def refresh_detail_panel(path):
        if not path:
            return

        # Preview
        ext = os.path.splitext(path)[1].lower()
        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".ico", ".webp"}
        if ext in image_exts:
            preview_image.src = path
            preview_image.visible = True
            preview_text.visible = False
        else:
            preview_image.visible = False
            preview_text.value = os.path.basename(path)
            preview_text.visible = True

        # Tags
        refresh_tag_display(path)

        # Metadata in background
        meta_text.value = "*Henter metadata...*"
        page.update()

        def load_meta():
            meta = extract_metadata(path)
            lines = []
            for key, value in meta.items():
                lines.append(f"**{key}:** {value}")
            meta_text.value = "\n\n".join(lines) if lines else "*Ingen metadata*"
            page.update()

        Thread(target=load_meta, daemon=True).start()

    def refresh_tag_display(path):
        tags = tag_store.get_tags(path)
        tag_display.value = ", ".join(tags) if tags else "Ingen tags"

    # --- Tagging ---

    def add_tag(e):
        path = selected_path_ref["current"]
        tag = (tag_combo.value or "").strip()
        if path and tag:
            tag_store.add_tag(path, tag)
            refresh_tag_display(path)
            update_tag_in_table(path)
            tag_combo.value = ""
            page.update()

    def remove_tag(e):
        path = selected_path_ref["current"]
        tag = (tag_combo.value or "").strip()
        if path and tag:
            tag_store.remove_tag(path, tag)
            refresh_tag_display(path)
            update_tag_in_table(path)
            tag_combo.value = ""
            page.update()

    def make_quick_tagger(tag):
        def handler(e):
            path = selected_path_ref["current"]
            if path:
                tag_store.add_tag(path, tag)
                refresh_tag_display(path)
                update_tag_in_table(path)
                page.update()
        return handler

    def update_tag_in_table(path):
        tags = tag_store.get_tags(path)
        for row in results_table.rows:
            path_cell = row.cells[6].content
            if hasattr(path_cell, "value") and path_cell.value == path:
                row.cells[5].content.value = ", ".join(tags)
                break

    # --- Search ---

    def add_result(info: dict):
        results_data.append(info)
        warnings = info.get("warnings", [])
        warn_text = "; ".join(warnings) if warnings else ""
        row_color = ft.Colors.AMBER_50 if warnings else None
        tags = tag_store.get_tags(info["path"])

        results_table.rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(info["name"])),
                    ft.DataCell(ft.Text(info["ext"])),
                    ft.DataCell(ft.Text(format_size(info["size"]))),
                    ft.DataCell(ft.Text(info["modified"])),
                    ft.DataCell(ft.Text(warn_text, color=ft.Colors.ORANGE_800 if warnings else None, size=11)),
                    ft.DataCell(ft.Text(", ".join(tags))),
                    ft.DataCell(ft.Text(info["path"], size=11)),
                ],
                color=row_color,
                on_select_changed=on_row_selected(info["path"]),
            )
        )
        page.update()

    def generate_report():
        data = results_data
        total = len(data)
        total_size = sum(r["size"] for r in data)

        lines = [
            "## Kvalitetsrapport\n",
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
        update_case_report()
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

    # --- Duplicate check ---

    def run_duplicate_check(e):
        dup_btn.disabled = True
        status_text.value = "Søger efter dubletter (beregner hash)..."
        page.update()

        def do_check():
            duplicates = find_duplicates(results_data)

            dup_paths = set()
            for group in duplicates.values():
                for f in group:
                    dup_paths.add(f["path"])

            for row in results_table.rows:
                path_cell = row.cells[6].content
                if hasattr(path_cell, "value") and path_cell.value in dup_paths:
                    row.color = ft.Colors.RED_50

            lines = [report_text.value, "\n### Dubletter\n"]
            if duplicates:
                total_dup = sum(len(g) for g in duplicates.values())
                wasted = sum(sum(f["size"] for f in group[1:]) for group in duplicates.values())
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

    # --- CSV Export ---

    def export_csv_action(e):
        def on_save_result(e: ft.FilePickerResultEvent):
            if not e.path:
                return
            path = e.path
            if not path.endswith(".csv"):
                path += ".csv"

            case_num = (case_input.value or "").strip()

            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Filnavn", "Type", "Størrelse (bytes)", "Ændret", "Advarsler", "Tags", "Sagsnr.", "Fuld sti"])
                for info in results_data:
                    warnings = "; ".join(info.get("warnings", []))
                    tags = ", ".join(tag_store.get_tags(info["path"]))
                    folder_case = tag_store.get_case_number(os.path.dirname(info["path"])) or case_num
                    writer.writerow([
                        info["name"], info["ext"], info["size"], info["modified"],
                        warnings, tags, folder_case, info["path"],
                    ])
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

    # --- Wire up ---
    search_btn.on_click = start_search
    search_input.on_submit = start_search
    export_btn.on_click = export_csv_action
    dup_btn.on_click = run_duplicate_check

    browse_btn = ft.ElevatedButton("Gennemse...", on_click=pick_directory)
    save_case_btn = ft.ElevatedButton("Gem sagsnr.", on_click=save_case_number)

    # Detail panel (right side)
    detail_panel = ft.Container(
        width=300,
        content=ft.Column([
            ft.Text("Forhåndsvisning", weight=ft.FontWeight.BOLD, size=14),
            preview_image,
            preview_text,
            ft.Divider(),
            ft.Text("Metadata", weight=ft.FontWeight.BOLD, size=14),
            meta_text,
            ft.Divider(),
            ft.Text("Tags", weight=ft.FontWeight.BOLD, size=14),
            tag_display,
            ft.Row([
                tag_combo,
                ft.IconButton(ft.Icons.ADD, on_click=add_tag, tooltip="Tilføj tag"),
                ft.IconButton(ft.Icons.REMOVE, on_click=remove_tag, tooltip="Fjern tag"),
            ]),
            ft.Row([
                ft.OutlinedButton("ESDH-klar", on_click=make_quick_tagger("ESDH-klar"),
                                  style=ft.ButtonStyle(padding=5)),
                ft.OutlinedButton("Konvertér", on_click=make_quick_tagger("Skal konverteres"),
                                  style=ft.ButtonStyle(padding=5)),
                ft.OutlinedButton("Arkivér", on_click=make_quick_tagger("Arkivér"),
                                  style=ft.ButtonStyle(padding=5)),
                ft.OutlinedButton("Slet", on_click=make_quick_tagger("Slet"),
                                  style=ft.ButtonStyle(padding=5)),
            ], wrap=True),
        ], scroll=ft.ScrollMode.AUTO),
        padding=ft.padding.only(left=10),
    )

    # Main layout
    main_content = ft.Row([
        ft.Column([tabs], expand=True),
        detail_panel,
    ], expand=True)

    page.add(
        ft.Row([dir_input, browse_btn]),
        ft.Row([case_input, save_case_btn]),
        ft.Row([search_input, recursive_cb, search_btn]),
        ft.Row([ext_input] + ext_buttons),
        ft.Divider(),
        main_content,
        ft.Divider(),
        ft.Row([export_btn, dup_btn, ft.Container(expand=True), status_text]),
    )

    # Initial load
    load_case_number()
    update_case_report()
