"""Main window UI for PySide6 file search app."""

import csv
import os
import subprocess
import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QFileDialog, QStatusBar,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTabWidget, QTextEdit, QSplitter, QGroupBox, QFormLayout, QInputDialog,
    QScrollArea, QComboBox,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPixmap
from searcher import FileSearcher
from validator import find_duplicates, format_size
from metadata import extract_metadata
from tagger import TagStore

WARN_COLOR = QColor(255, 240, 220)
DUPLICATE_COLOR = QColor(255, 220, 220)


class MetadataWorker(QThread):
    done = Signal(dict)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        meta = extract_metadata(self.path)
        self.done.emit(meta)


class DupWorker(QThread):
    done = Signal(dict)

    def __init__(self, results):
        super().__init__()
        self.results = results

    def run(self):
        self.done.emit(find_duplicates(self.results))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESDH File Scanner (PySide6)")
        self.resize(1200, 750)
        self.searcher = None
        self._results_data = []
        self._meta_worker = None
        self._dup_worker = None
        self.tag_store = TagStore()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Directory picker
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Mappe:"))
        self.dir_input = QLineEdit(os.path.expanduser("~"))
        dir_row.addWidget(self.dir_input)
        browse_btn = QPushButton("Gennemse...")
        browse_btn.clicked.connect(self.pick_directory)
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        # Case number row
        case_row = QHBoxLayout()
        case_row.addWidget(QLabel("Sagsnr:"))
        self.case_input = QLineEdit()
        self.case_input.setPlaceholderText("Tildel sagsnr. til den valgte mappe...")
        case_row.addWidget(self.case_input)
        save_case_btn = QPushButton("Gem sagsnr.")
        save_case_btn.clicked.connect(self._save_case_number)
        case_row.addWidget(save_case_btn)
        layout.addLayout(case_row)

        # Search bar
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Søg:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Skriv filnavn eller del af filnavn (tom = alle filer)...")
        self.search_input.returnPressed.connect(self.start_search)
        search_row.addWidget(self.search_input)
        self.recursive_cb = QCheckBox("Inkl. undermapper")
        self.recursive_cb.setChecked(True)
        search_row.addWidget(self.recursive_cb)
        self.search_btn = QPushButton("Søg")
        self.search_btn.clicked.connect(self.start_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        # File type filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filtyper:"))
        self.ext_input = QLineEdit()
        self.ext_input.setPlaceholderText("f.eks. pdf,docx,xlsx (tom = alle filtyper)")
        filter_row.addWidget(self.ext_input)
        for ext in ["pdf", "docx", "xlsx", "msg"]:
            btn = QPushButton(f".{ext}")
            btn.setCheckable(True)
            btn.setMaximumWidth(60)
            btn.clicked.connect(self._make_ext_toggler(ext))
            filter_row.addWidget(btn)
        layout.addLayout(filter_row)

        # Main content: splitter with table on left, detail panel on right
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left side: tabs
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        left_layout.addWidget(self.tabs)

        # Tab 1: Results table
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Filnavn", "Type", "Størrelse", "Ændret", "Advarsler", "Tags", "Sti"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._on_table_double_click)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.tabs.addTab(self.table, "Resultater")

        # Tab 2: Quality report
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.tabs.addTab(self.report, "Kvalitetsrapport")

        # Tab 3: Case mappings
        self.case_report = QTextEdit()
        self.case_report.setReadOnly(True)
        self.tabs.addTab(self.case_report, "Sagsnr.-oversigt")

        splitter.addWidget(left_widget)

        # Right side: detail/preview panel
        right_widget = QWidget()
        right_widget.setMinimumWidth(280)
        right_widget.setMaximumWidth(400)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 0, 0)

        # Preview area
        preview_group = QGroupBox("Forhåndsvisning")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_label = QLabel("Vælg en fil for at se detaljer")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(150)
        self.preview_label.setStyleSheet("background: #f5f5f5; border: 1px solid #ddd; padding: 4px;")
        preview_layout.addWidget(self.preview_label)
        right_layout.addWidget(preview_group)

        # Metadata area
        meta_group = QGroupBox("Metadata")
        meta_layout = QVBoxLayout(meta_group)
        self.meta_text = QTextEdit()
        self.meta_text.setReadOnly(True)
        self.meta_text.setMaximumHeight(200)
        meta_layout.addWidget(self.meta_text)
        right_layout.addWidget(meta_group)

        # Tagging area
        tag_group = QGroupBox("Tags")
        tag_layout = QVBoxLayout(tag_group)
        self.tag_display = QLabel("Ingen tags")
        tag_layout.addWidget(self.tag_display)

        tag_input_row = QHBoxLayout()
        self.tag_combo = QComboBox()
        self.tag_combo.setEditable(True)
        self.tag_combo.setPlaceholderText("Skriv eller vælg tag...")
        tag_input_row.addWidget(self.tag_combo)
        add_tag_btn = QPushButton("+")
        add_tag_btn.setMaximumWidth(30)
        add_tag_btn.clicked.connect(self._add_tag)
        tag_input_row.addWidget(add_tag_btn)
        remove_tag_btn = QPushButton("-")
        remove_tag_btn.setMaximumWidth(30)
        remove_tag_btn.clicked.connect(self._remove_tag)
        tag_input_row.addWidget(remove_tag_btn)
        tag_layout.addLayout(tag_input_row)

        # Predefined tag buttons
        predefined_row = QHBoxLayout()
        for tag in ["ESDH-klar", "Skal konverteres", "Arkivér", "Slet"]:
            btn = QPushButton(tag)
            btn.setStyleSheet("font-size: 10px; padding: 2px 6px;")
            btn.clicked.connect(self._make_quick_tagger(tag))
            predefined_row.addWidget(btn)
        tag_layout.addLayout(predefined_row)

        right_layout.addWidget(tag_group)
        right_layout.addStretch()

        splitter.addWidget(right_widget)
        splitter.setSizes([800, 300])

        # Bottom row
        bottom_row = QHBoxLayout()
        self.export_btn = QPushButton("Eksportér til CSV...")
        self.export_btn.clicked.connect(self.export_csv)
        self.export_btn.setEnabled(False)
        bottom_row.addWidget(self.export_btn)

        self.dup_btn = QPushButton("Find dubletter")
        self.dup_btn.clicked.connect(self.run_duplicate_check)
        self.dup_btn.setEnabled(False)
        bottom_row.addWidget(self.dup_btn)

        bottom_row.addStretch()
        layout.addLayout(bottom_row)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Klar.")

        # Load case number for initial directory
        self._load_case_number()
        self.dir_input.textChanged.connect(self._load_case_number)

    # --- Case number ---

    def _load_case_number(self):
        directory = self.dir_input.text().strip()
        case = self.tag_store.get_case_number(directory) if directory else ""
        self.case_input.setText(case)

    def _save_case_number(self):
        directory = self.dir_input.text().strip()
        case = self.case_input.text().strip()
        if directory:
            self.tag_store.set_case_number(directory, case)
            self.status.showMessage(f"Sagsnr. '{case}' gemt for {directory}")
            self._update_case_report()

    def _update_case_report(self):
        mappings = self.tag_store.get_all_case_mappings()
        if not mappings:
            self.case_report.setHtml("<p>Ingen sagsnr.-mappinger gemt endnu.</p>")
            return
        lines = ["<h2>Sagsnr.-oversigt</h2><table border='1' cellpadding='4' cellspacing='0'>"]
        lines.append("<tr><th>Mappe</th><th>Sagsnr.</th></tr>")
        for folder, case in sorted(mappings.items()):
            lines.append(f"<tr><td>{folder}</td><td><b>{case}</b></td></tr>")
        lines.append("</table>")
        self.case_report.setHtml("\n".join(lines))

    # --- Tagging ---

    def _selected_file_path(self) -> str:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return ""
        row = rows[0].row()
        item = self.table.item(row, 6)
        return item.text() if item else ""

    def _refresh_tag_display(self):
        path = self._selected_file_path()
        if not path:
            self.tag_display.setText("Ingen fil valgt")
            return
        tags = self.tag_store.get_tags(path)
        self.tag_display.setText(", ".join(tags) if tags else "Ingen tags")
        # Update tag column in table
        self._update_tag_column(path, tags)
        # Refresh combo box with all known tags
        self.tag_combo.clear()
        self.tag_combo.addItems(self.tag_store.all_tags())

    def _update_tag_column(self, path: str, tags: list):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 6)
            if item and item.text() == path:
                self.table.item(row, 5).setText(", ".join(tags))
                break

    def _add_tag(self):
        path = self._selected_file_path()
        tag = self.tag_combo.currentText().strip()
        if path and tag:
            self.tag_store.add_tag(path, tag)
            self._refresh_tag_display()

    def _remove_tag(self):
        path = self._selected_file_path()
        tag = self.tag_combo.currentText().strip()
        if path and tag:
            self.tag_store.remove_tag(path, tag)
            self._refresh_tag_display()

    def _make_quick_tagger(self, tag: str):
        def handler():
            path = self._selected_file_path()
            if path:
                self.tag_store.add_tag(path, tag)
                self._refresh_tag_display()
        return handler

    # --- Selection / Preview / Metadata ---

    def _on_selection_changed(self):
        path = self._selected_file_path()
        if not path:
            return

        self._refresh_tag_display()

        # Show image preview for supported types
        ext = os.path.splitext(path)[1].lower()
        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".ico", ".webp"}
        if ext in image_exts:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.preview_label.width() - 10, 150,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.preview_label.setPixmap(scaled)
            else:
                self.preview_label.setText("Kunne ikke vise billede")
        else:
            self.preview_label.setText(os.path.basename(path))

        # Load metadata in background
        self.meta_text.setPlainText("Henter metadata...")
        self._meta_worker = MetadataWorker(path)
        self._meta_worker.done.connect(self._show_metadata)
        self._meta_worker.start()

    def _show_metadata(self, meta: dict):
        lines = []
        for key, value in meta.items():
            lines.append(f"<b>{key}:</b> {value}")
        self.meta_text.setHtml("<br>".join(lines) if lines else "Ingen metadata fundet")

    # --- Ext toggler ---

    def _make_ext_toggler(self, ext: str):
        def toggler(checked):
            current = [e.strip() for e in self.ext_input.text().split(",") if e.strip()]
            if checked:
                if ext not in current:
                    current.append(ext)
            else:
                current = [e for e in current if e != ext]
            self.ext_input.setText(",".join(current))
        return toggler

    def _parse_extensions(self) -> list:
        text = self.ext_input.text().strip()
        if not text:
            return None
        return [e.strip().lower().lstrip(".") for e in text.split(",") if e.strip()]

    # --- Directory picker ---

    def pick_directory(self):
        path = QFileDialog.getExistingDirectory(self, "Vælg mappe", self.dir_input.text())
        if path:
            self.dir_input.setText(path)

    # --- Search ---

    def start_search(self):
        directory = self.dir_input.text().strip()
        if not directory:
            return

        if self.searcher and self.searcher.isRunning():
            self.searcher.stop()
            self.searcher.wait()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._results_data = []
        self.report.clear()
        self.search_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.dup_btn.setEnabled(False)
        self.status.showMessage("Søger...")

        query = self.search_input.text().strip()
        extensions = self._parse_extensions()

        self.searcher = FileSearcher(directory, query, self.recursive_cb.isChecked(), extensions)
        self.searcher.result_found.connect(self.add_result)
        self.searcher.search_done.connect(self.on_search_done)
        self.searcher.start()

    def add_result(self, info: dict):
        self._results_data.append(info)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(info["name"]))
        self.table.setItem(row, 1, QTableWidgetItem(info["ext"]))

        size_item = QTableWidgetItem(format_size(info["size"]))
        size_item.setData(Qt.ItemDataRole.UserRole, info["size"])
        self.table.setItem(row, 2, size_item)

        self.table.setItem(row, 3, QTableWidgetItem(info["modified"]))

        warnings = info.get("warnings", [])
        warn_text = "; ".join(warnings) if warnings else ""
        self.table.setItem(row, 4, QTableWidgetItem(warn_text))

        # Tags
        tags = self.tag_store.get_tags(info["path"])
        self.table.setItem(row, 5, QTableWidgetItem(", ".join(tags)))

        self.table.setItem(row, 6, QTableWidgetItem(info["path"]))

        if warnings:
            for col in range(7):
                item = self.table.item(row, col)
                if item:
                    item.setBackground(WARN_COLOR)

    def on_search_done(self, count: int):
        self.search_btn.setEnabled(True)
        self.export_btn.setEnabled(count > 0)
        self.dup_btn.setEnabled(count > 0)
        self.table.setSortingEnabled(True)

        total_size = sum(r["size"] for r in self._results_data)
        warn_count = sum(1 for r in self._results_data if r.get("warnings"))
        self.status.showMessage(
            f"Fandt {count} fil(er) – {format_size(total_size)} – {warn_count} med advarsler"
        )

        self._generate_report()
        self._update_case_report()

    def _generate_report(self):
        lines = ["<h2>Kvalitetsrapport</h2>"]
        data = self._results_data

        total = len(data)
        total_size = sum(r["size"] for r in data)
        lines.append(f"<p><b>Samlet:</b> {total} filer, {format_size(total_size)}</p>")

        ext_counts = {}
        for r in data:
            ext = r["ext"] or "(ingen)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
        lines.append("<h3>Filtyper</h3><ul>")
        for ext, cnt in sorted(ext_counts.items(), key=lambda x: -x[1]):
            lines.append(f"<li><b>{ext}</b>: {cnt} filer</li>")
        lines.append("</ul>")

        warn_files = [r for r in data if r.get("warnings")]
        if warn_files:
            lines.append(f"<h3>Advarsler ({len(warn_files)} filer)</h3>")
            warn_types = {}
            for r in warn_files:
                for w in r["warnings"]:
                    warn_types.setdefault(w, []).append(r)
            for wtype, files in sorted(warn_types.items(), key=lambda x: -len(x[1])):
                lines.append(f"<h4>{wtype} ({len(files)})</h4><ul>")
                for f in files[:20]:
                    lines.append(f"<li>{f['name']} <span style='color:gray'>– {f['path']}</span></li>")
                if len(files) > 20:
                    lines.append(f"<li><i>...og {len(files) - 20} flere</i></li>")
                lines.append("</ul>")
        else:
            lines.append("<h3>Ingen advarsler fundet</h3>")

        self.report.setHtml("\n".join(lines))

    # --- Duplicates ---

    def run_duplicate_check(self):
        self.status.showMessage("Søger efter dubletter (beregner hash)...")
        self.dup_btn.setEnabled(False)

        def on_dup_done(duplicates):
            self.dup_btn.setEnabled(True)

            dup_paths = set()
            for group in duplicates.values():
                for f in group:
                    dup_paths.add(f["path"])

            for row in range(self.table.rowCount()):
                path_item = self.table.item(row, 6)
                if path_item and path_item.text() in dup_paths:
                    for col in range(7):
                        item = self.table.item(row, col)
                        if item:
                            item.setBackground(DUPLICATE_COLOR)

            html = self.report.toHtml()
            lines = ["<h3>Dubletter</h3>"]
            if duplicates:
                total_dup = sum(len(g) for g in duplicates.values())
                wasted = sum(
                    sum(f["size"] for f in group[1:])
                    for group in duplicates.values()
                )
                lines.append(
                    f"<p><b>{total_dup} filer</b> i <b>{len(duplicates)} grupper</b> "
                    f"– spildplads: <b>{format_size(wasted)}</b></p>"
                )
                for i, (h, group) in enumerate(duplicates.items(), 1):
                    lines.append(f"<h4>Gruppe {i} ({len(group)} filer, {format_size(group[0]['size'])} hver)</h4><ul>")
                    for f in group:
                        lines.append(f"<li>{f['path']}</li>")
                    lines.append("</ul>")
            else:
                lines.append("<p>Ingen dubletter fundet.</p>")

            self.report.setHtml(html + "\n".join(lines))
            self.tabs.setCurrentIndex(1)

            dup_count = sum(len(g) for g in duplicates.values()) if duplicates else 0
            self.status.showMessage(
                f"Dublet-tjek færdig – {dup_count} dubletter i {len(duplicates)} grupper"
            )

        self._dup_worker = DupWorker(self._results_data)
        self._dup_worker.done.connect(on_dup_done)
        self._dup_worker.start()

    # --- Open file ---

    def _on_table_double_click(self, index):
        row = index.row()
        path_item = self.table.item(row, 6)
        if not path_item:
            return
        path = path_item.text()
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])

    # --- CSV Export ---

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Gem CSV-fil", "filsøgning.csv", "CSV-filer (*.csv)"
        )
        if not path:
            return

        case_num = self.case_input.text().strip()

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Filnavn", "Type", "Størrelse (bytes)", "Ændret", "Advarsler", "Tags", "Sagsnr.", "Fuld sti"])
            for info in self._results_data:
                warnings = "; ".join(info.get("warnings", []))
                tags = ", ".join(self.tag_store.get_tags(info["path"]))
                folder_case = self.tag_store.get_case_number(os.path.dirname(info["path"])) or case_num
                writer.writerow([
                    info["name"], info["ext"], info["size"], info["modified"],
                    warnings, tags, folder_case, info["path"],
                ])

        self.status.showMessage(f"Eksporteret {len(self._results_data)} rækker til {path}")
