"""Main UI builder for Flet ESDH File Scanner."""

import csv
import os
import subprocess
import sys
from threading import Thread
import flet as ft
from database import FileIndex
from batch import BatchIndexer, BatchMetadataExtractor, BatchHasher
from metadata import extract_metadata
from exporter import export_csv, export_html_report
from validator import format_size

STATUSES = ["ny", "ESDH-klar", "skal konverteres", "arkiveret", "slettes", "behandlet"]


def build_ui(page: ft.Page):
    db = FileIndex()
    workers = []
    results_data_ref = {"files": []}
    selected_path_ref = {"current": ""}

    # === Results table ===
    results_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Filnavn")),
            ft.DataColumn(ft.Text("Type")),
            ft.DataColumn(ft.Text("Størrelse"), numeric=True),
            ft.DataColumn(ft.Text("Ændret")),
            ft.DataColumn(ft.Text("Status")),
            ft.DataColumn(ft.Text("Advarsler")),
            ft.DataColumn(ft.Text("Tags")),
            ft.DataColumn(ft.Text("Sti")),
        ],
        expand=True,
    )
    results_scroll = ft.ListView(expand=True)
    results_scroll.controls.append(results_table)

    # === Dashboard / Report ===
    dashboard_md = ft.Markdown("", expand=True, selectable=True)
    dashboard_scroll = ft.ListView(expand=True)
    dashboard_scroll.controls.append(dashboard_md)

    scan_history_md = ft.Markdown("", expand=True, selectable=True)
    history_scroll = ft.ListView(expand=True)
    history_scroll.controls.append(scan_history_md)

    tabs = ft.Tabs(
        selected_index=0,
        tabs=[
            ft.Tab(text="Resultater", content=results_scroll),
            ft.Tab(text="Dashboard", content=dashboard_scroll),
            ft.Tab(text="Scan-historik", content=history_scroll),
        ],
        expand=True,
    )

    # === Detail panel ===
    preview_image = ft.Image(visible=False, width=260, height=140, fit=ft.ImageFit.CONTAIN)
    preview_text = ft.Text("Vælg en fil", size=12)
    meta_md = ft.Markdown("", selectable=True)
    tag_display = ft.Text("Ingen tags", size=12)
    tag_input = ft.TextField(label="Tag", hint_text="Skriv tag...", expand=True, dense=True)
    status_combo = ft.Dropdown(
        options=[ft.dropdown.Option(s) for s in STATUSES],
        value="ny", dense=True, width=150,
    )
    bulk_tag_input = ft.TextField(hint_text="Tag alle valgte...", expand=True, dense=True)

    # === Controls ===
    status_text = ft.Text("Klar.", size=12)
    progress_bar = ft.ProgressBar(visible=False, expand=True)
    progress_label = ft.Text("", size=11, visible=False)

    dir_input = ft.TextField(value=os.path.expanduser("~"), label="Mappe", expand=True)
    case_input = ft.TextField(label="Sagsnr.", hint_text="Sagsnr.", width=150)
    search_input = ft.TextField(label="Søg", hint_text="Filnavn (tom = alle)", expand=True)
    ext_input = ft.TextField(label="Filtyper", hint_text="pdf,docx,xlsx", width=150)
    recursive_cb = ft.Checkbox(label="Inkl. undermapper", value=True)

    status_filter = ft.Dropdown(
        options=[ft.dropdown.Option("", "(alle)")] + [ft.dropdown.Option(s) for s in STATUSES],
        value="", dense=True, width=130, label="Status",
    )
    tag_filter = ft.Dropdown(
        options=[ft.dropdown.Option("", "(alle)")],
        value="", dense=True, width=130, label="Tag",
    )
    warn_cb = ft.Checkbox(label="Kun advarsler", value=False)

    # ===== Helpers =====

    def load_case_number():
        d = (dir_input.value or "").strip()
        case_input.value = db.get_case_number(d) if d else ""

    def refresh_tag_filter():
        current = tag_filter.value
        tag_filter.options = [ft.dropdown.Option("", "(alle)")]
        for t in db.all_tags():
            tag_filter.options.append(ft.dropdown.Option(t))
        tag_filter.value = current if current else ""

    def refresh_dashboard():
        stats = db.get_stats()
        lines = [
            "## ESDH File Scanner – Dashboard\n",
            f"**Filer i indeks:** {stats['total_files']}",
            f"**Samlet størrelse:** {format_size(stats['total_size'])}",
            f"**Metadata udtrukket:** {stats['metadata_extracted']} / {stats['total_files']}",
            f"**Med advarsler:** {stats['with_warnings']}",
            f"**Med tags:** {stats['with_tags']}\n",
        ]

        if stats["by_status"]:
            lines.append("### Status-fordeling\n")
            for s, c in stats["by_status"].items():
                lines.append(f"- **{s}**: {c}")

        if stats["by_ext"]:
            lines.append("\n### Filtyper\n")
            lines.append("| Type | Antal | Størrelse |")
            lines.append("|---|---|---|")
            for e in stats["by_ext"]:
                lines.append(f"| {e['ext'] or '(ingen)'} | {e['count']} | {format_size(e['size'])} |")

        if stats["by_tag"]:
            lines.append("\n### Tags\n")
            for t, c in stats["by_tag"].items():
                lines.append(f"- **{t}**: {c} filer")

        dups = db.find_duplicates()
        if dups:
            total_dup = sum(len(g) for g in dups)
            wasted = sum(sum(f["size"] for f in g[1:]) for g in dups)
            lines.append(f"\n### Dubletter\n")
            lines.append(f"**{total_dup} filer** i **{len(dups)} grupper** – spildplads: **{format_size(wasted)}**")

        cases = db.get_all_case_mappings()
        if cases:
            lines.append("\n### Sagsnr.\n")
            lines.append("| Mappe | Sagsnr. |")
            lines.append("|---|---|")
            for folder, case in sorted(cases.items()):
                lines.append(f"| {folder} | **{case}** |")

        dashboard_md.value = "\n".join(lines)

    def refresh_scan_history():
        history = db.get_scan_history()
        if not history:
            scan_history_md.value = "Ingen scanninger endnu."
            return
        lines = ["## Scan-historik\n",
                  "| Tidspunkt | Mappe | Filer | Nye | Opdaterede | Uændrede |",
                  "|---|---|---|---|---|---|"]
        for s in history:
            lines.append(
                f"| {s['started_at'][:16]} | {s['scan_root']} | "
                f"{s['files_found']} | {s['files_new']} | "
                f"{s['files_updated']} | {s['files_unchanged']} |"
            )
        scan_history_md.value = "\n".join(lines)

    def refresh_table(e=None):
        query = (search_input.value or "").strip()
        ext = (ext_input.value or "").strip()
        status = status_filter.value or ""
        tag = tag_filter.value or ""
        has_warnings = True if warn_cb.value else None

        filters = {}
        if query: filters["query"] = query
        if ext: filters["ext"] = ext
        if status: filters["status"] = status
        if tag: filters["tag"] = tag
        if has_warnings: filters["has_warnings"] = has_warnings

        files = db.search(**filters)
        results_data_ref["files"] = files
        results_table.rows.clear()

        for f in files:
            warnings = f.get("warnings", [])
            warn_text = "; ".join(warnings)
            tags = ", ".join(f.get("tags", []))
            color = ft.Colors.AMBER_50 if warnings else None

            results_table.rows.append(ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(f["name"])),
                    ft.DataCell(ft.Text(f["ext"])),
                    ft.DataCell(ft.Text(format_size(f["size"]))),
                    ft.DataCell(ft.Text(f["modified"])),
                    ft.DataCell(ft.Text(f.get("status", ""))),
                    ft.DataCell(ft.Text(warn_text, color=ft.Colors.ORANGE_800 if warnings else None, size=11)),
                    ft.DataCell(ft.Text(tags)),
                    ft.DataCell(ft.Text(f["path"], size=10)),
                ],
                color=color,
                on_select_changed=make_row_selector(f["path"]),
            ))

        status_text.value = f"Viser {len(files)} filer"
        page.update()

    # ===== Row selection =====

    def make_row_selector(path):
        def handler(e):
            selected_path_ref["current"] = path
            refresh_detail(path)
        return handler

    def refresh_detail(path):
        ext = os.path.splitext(path)[1].lower()
        img_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif"}
        if ext in img_exts:
            preview_image.src = path
            preview_image.visible = True
            preview_text.visible = False
        else:
            preview_image.visible = False
            preview_text.value = os.path.basename(path)
            preview_text.visible = True

        f = db.get_file(path)
        if f:
            meta = f.get("metadata", {})
            if meta:
                meta_md.value = "\n\n".join(f"**{k}:** {v}" for k, v in meta.items())
            elif not f.get("metadata_extracted"):
                meta_md.value = "*Metadata ikke udtrukket endnu*"
            else:
                meta_md.value = "*Ingen metadata*"

            status_combo.value = f.get("status", "ny")

        tags = db.get_tags(path)
        tag_display.value = ", ".join(tags) if tags else "Ingen tags"
        page.update()

    # ===== Scanning =====

    def start_scan(e):
        directory = (dir_input.value or "").strip()
        if not directory:
            return

        ext_text = (ext_input.value or "").strip()
        extensions = [x.strip() for x in ext_text.split(",") if x.strip()] if ext_text else None

        progress_bar.visible = True
        progress_label.visible = True
        progress_bar.value = 0
        page.update()

        def on_progress(current, total, filename):
            progress_bar.value = current / total if total else 0
            progress_label.value = f"{current}/{total} – {filename}"
            page.update()

        def on_done(stats):
            progress_bar.visible = False
            progress_label.visible = False
            status_text.value = (
                f"Scan færdig: {stats['total']} filer – "
                f"{stats['new']} nye, {stats['updated']} opdaterede, "
                f"{stats['unchanged']} uændrede"
            )
            refresh_table()
            refresh_dashboard()
            refresh_scan_history()
            refresh_tag_filter()
            page.update()

        w = BatchIndexer(db, directory, recursive_cb.value, extensions,
                         on_progress=on_progress, on_done=on_done)
        w.start()
        workers.append(w)

    def start_metadata(e):
        progress_bar.visible = True
        progress_label.visible = True
        progress_bar.value = 0
        page.update()

        def on_progress(c, t, name):
            progress_bar.value = c / t if t else 0
            progress_label.value = f"Metadata: {c}/{t} – {name}"
            page.update()

        def on_done(count):
            progress_bar.visible = False
            progress_label.visible = False
            status_text.value = f"Metadata udtrukket for {count} filer"
            refresh_dashboard()
            page.update()

        w = BatchMetadataExtractor(db, on_progress=on_progress, on_done=on_done)
        w.start()
        workers.append(w)

    def start_hashing(e):
        progress_bar.visible = True
        progress_label.visible = True
        progress_bar.value = 0
        page.update()

        def on_progress(c, t, name):
            progress_bar.value = c / t if t else 0
            progress_label.value = f"Hash: {c}/{t} – {name}"
            page.update()

        def on_done(count):
            progress_bar.visible = False
            progress_label.visible = False
            dups = db.find_duplicates()
            total_dup = sum(len(g) for g in dups)
            status_text.value = f"Hash: {count} filer – {total_dup} dubletter"
            refresh_dashboard()
            page.update()

        w = BatchHasher(db, on_progress=on_progress, on_done=on_done)
        w.start()
        workers.append(w)

    # ===== Case number =====

    def save_case(e):
        d = (dir_input.value or "").strip()
        c = (case_input.value or "").strip()
        if d:
            db.set_case_number(d, c)
            status_text.value = f"Sagsnr. '{c}' gemt"
            page.update()

    def on_dir_change(e):
        load_case_number()
        page.update()

    dir_input.on_change = on_dir_change

    # ===== Tags =====

    def add_tag(e):
        path = selected_path_ref["current"]
        tag = (tag_input.value or "").strip()
        if path and tag:
            db.add_tag(path, tag)
            tag_input.value = ""
            refresh_detail(path)
            refresh_tag_filter()
            page.update()

    def remove_tag(e):
        path = selected_path_ref["current"]
        tag = (tag_input.value or "").strip()
        if path and tag:
            db.remove_tag(path, tag)
            tag_input.value = ""
            refresh_detail(path)
            refresh_tag_filter()
            page.update()

    def make_quick_tagger(tag):
        def handler(e):
            path = selected_path_ref["current"]
            if path:
                db.add_tag(path, tag)
                refresh_detail(path)
                refresh_tag_filter()
                page.update()
        return handler

    def bulk_tag(e):
        tag = (bulk_tag_input.value or "").strip()
        if not tag:
            return
        # Tag all currently shown files
        paths = [f["path"] for f in results_data_ref["files"]]
        if paths:
            db.bulk_add_tag(paths, tag)
            bulk_tag_input.value = ""
            status_text.value = f"Tag '{tag}' tilføjet til {len(paths)} filer"
            refresh_table()
            refresh_tag_filter()
            page.update()

    # ===== Status =====

    def set_status(e):
        path = selected_path_ref["current"]
        if path and status_combo.value:
            db.set_status(path, status_combo.value)
            db.commit()
            status_text.value = f"Status sat til '{status_combo.value}'"
            page.update()

    def bulk_set_status(e):
        if not status_combo.value:
            return
        paths = [f["path"] for f in results_data_ref["files"]]
        if paths:
            db.bulk_set_status(paths, status_combo.value)
            status_text.value = f"Status '{status_combo.value}' sat på {len(paths)} filer"
            refresh_table()

    # ===== Export =====

    def do_export_csv(e):
        def on_save(e: ft.FilePickerResultEvent):
            if not e.path:
                return
            path = e.path if e.path.endswith(".csv") else e.path + ".csv"
            filters = {}
            q = (search_input.value or "").strip()
            if q: filters["query"] = q
            ext = (ext_input.value or "").strip()
            if ext: filters["ext"] = ext
            s = status_filter.value
            if s: filters["status"] = s
            t = tag_filter.value
            if t: filters["tag"] = t

            count = export_csv(db, path, filters, include_metadata=True)
            status_text.value = f"Eksporteret {count} filer til {path}"
            page.update()

        picker = ft.FilePicker(on_result=on_save)
        page.overlay.append(picker)
        page.update()
        picker.save_file(dialog_title="Gem CSV", file_name="esdh_filscan.csv",
                         allowed_extensions=["csv"])

    def do_export_html(e):
        def on_save(e: ft.FilePickerResultEvent):
            if not e.path:
                return
            path = e.path if e.path.endswith(".html") else e.path + ".html"
            export_html_report(db, path)
            status_text.value = f"Rapport gemt: {path}"
            page.update()

        picker = ft.FilePicker(on_result=on_save)
        page.overlay.append(picker)
        page.update()
        picker.save_file(dialog_title="Gem rapport", file_name="esdh_rapport.html",
                         allowed_extensions=["html"])

    # ===== Directory picker =====

    def pick_directory(e):
        def on_result(e: ft.FilePickerResultEvent):
            if e.path:
                dir_input.value = e.path
                load_case_number()
                page.update()
        picker = ft.FilePicker(on_result=on_result)
        page.overlay.append(picker)
        page.update()
        picker.get_directory_path(dialog_title="Vælg mappe",
                                  initial_directory=dir_input.value)

    # ===== Layout =====

    browse_btn = ft.ElevatedButton("Gennemse...", on_click=pick_directory)
    save_case_btn = ft.ElevatedButton("Gem", on_click=save_case)
    scan_btn = ft.ElevatedButton("Scan && indeksér", on_click=start_scan,
                                  style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_50))
    meta_btn = ft.ElevatedButton("Udtræk metadata", on_click=start_metadata)
    hash_btn = ft.ElevatedButton("Find dubletter", on_click=start_hashing)
    filter_btn = ft.ElevatedButton("Filtrer", on_click=refresh_table)
    csv_btn = ft.ElevatedButton("Eksportér CSV", on_click=do_export_csv)
    html_btn = ft.ElevatedButton("HTML-rapport", on_click=do_export_html)

    detail_panel = ft.Container(
        width=300,
        content=ft.Column([
            ft.Text("Forhåndsvisning", weight=ft.FontWeight.BOLD, size=13),
            preview_image, preview_text,
            ft.Divider(),
            ft.Text("Metadata", weight=ft.FontWeight.BOLD, size=13),
            meta_md,
            ft.Divider(),
            ft.Text("Status", weight=ft.FontWeight.BOLD, size=13),
            ft.Row([status_combo,
                    ft.ElevatedButton("Sæt", on_click=set_status),
                    ft.ElevatedButton("Alle viste", on_click=bulk_set_status)]),
            ft.Divider(),
            ft.Text("Tags", weight=ft.FontWeight.BOLD, size=13),
            tag_display,
            ft.Row([tag_input,
                    ft.IconButton(ft.Icons.ADD, on_click=add_tag, tooltip="Tilføj"),
                    ft.IconButton(ft.Icons.REMOVE, on_click=remove_tag, tooltip="Fjern")]),
            ft.Row([
                ft.OutlinedButton("ESDH-klar", on_click=make_quick_tagger("ESDH-klar"),
                                  style=ft.ButtonStyle(padding=4)),
                ft.OutlinedButton("Konvertér", on_click=make_quick_tagger("Skal konverteres"),
                                  style=ft.ButtonStyle(padding=4)),
                ft.OutlinedButton("Arkivér", on_click=make_quick_tagger("Arkivér"),
                                  style=ft.ButtonStyle(padding=4)),
                ft.OutlinedButton("Slet", on_click=make_quick_tagger("Slet"),
                                  style=ft.ButtonStyle(padding=4)),
            ], wrap=True),
            ft.Divider(),
            ft.Text("Bulk-tag (alle viste)", size=12),
            ft.Row([bulk_tag_input, ft.ElevatedButton("Tag alle", on_click=bulk_tag)]),
        ], scroll=ft.ScrollMode.AUTO),
        padding=ft.padding.only(left=10),
    )

    main_content = ft.Row([ft.Column([tabs], expand=True), detail_panel], expand=True)

    page.add(
        ft.Row([dir_input, browse_btn, case_input, save_case_btn]),
        ft.Row([search_input, ext_input, status_filter, tag_filter, warn_cb, filter_btn]),
        ft.Row([scan_btn, recursive_cb, meta_btn, hash_btn,
                ft.Container(expand=True), csv_btn, html_btn]),
        ft.Row([progress_bar, progress_label]),
        ft.Divider(),
        main_content,
        ft.Divider(),
        status_text,
    )

    # Initialize
    load_case_number()
    refresh_dashboard()
    refresh_scan_history()
    refresh_tag_filter()
