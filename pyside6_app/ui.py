"""Main window UI for PySide6 ESDH File Scanner."""

import csv
import os
import subprocess
import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QFileDialog, QStatusBar,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTabWidget, QTextEdit, QSplitter, QGroupBox, QProgressBar,
    QComboBox, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from database import FileIndex
from batch import BatchIndexer, BatchMetadataExtractor, BatchHasher
from metadata import extract_metadata
from exporter import export_csv, export_html_report, generate_html_report
from validator import format_size

WARN_COLOR = QColor(255, 240, 220)
DUP_COLOR = QColor(255, 220, 220)
STATUSES = ["ny", "ESDH-klar", "skal konverteres", "arkiveret", "slettes", "behandlet"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESDH File Scanner")
        self.resize(1250, 800)
        self.db = FileIndex()
        self._workers = []

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # === Top: Directory + Case number ===
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Mappe:"))
        self.dir_input = QLineEdit(os.path.expanduser("~"))
        top_row.addWidget(self.dir_input)
        browse_btn = QPushButton("Gennemse...")
        browse_btn.clicked.connect(self.pick_directory)
        top_row.addWidget(browse_btn)
        top_row.addWidget(QLabel("Sagsnr:"))
        self.case_input = QLineEdit()
        self.case_input.setMaximumWidth(150)
        self.case_input.setPlaceholderText("Sagsnr.")
        top_row.addWidget(self.case_input)
        save_case_btn = QPushButton("Gem")
        save_case_btn.setMaximumWidth(50)
        save_case_btn.clicked.connect(self._save_case_number)
        top_row.addWidget(save_case_btn)
        layout.addLayout(top_row)

        # === Filters + search ===
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Søg:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filnavn (tom = alle)")
        self.search_input.returnPressed.connect(self.refresh_table)
        filter_row.addWidget(self.search_input)

        filter_row.addWidget(QLabel("Type:"))
        self.ext_input = QLineEdit()
        self.ext_input.setPlaceholderText("pdf,docx,xlsx")
        self.ext_input.setMaximumWidth(120)
        filter_row.addWidget(self.ext_input)

        filter_row.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("(alle)", "")
        for s in STATUSES:
            self.status_filter.addItem(s, s)
        self.status_filter.setMaximumWidth(130)
        filter_row.addWidget(self.status_filter)

        filter_row.addWidget(QLabel("Tag:"))
        self.tag_filter = QComboBox()
        self.tag_filter.addItem("(alle)", "")
        self.tag_filter.setMaximumWidth(130)
        filter_row.addWidget(self.tag_filter)

        self.warn_cb = QCheckBox("Kun advarsler")
        filter_row.addWidget(self.warn_cb)

        filter_btn = QPushButton("Filtrer")
        filter_btn.clicked.connect(self.refresh_table)
        filter_row.addWidget(filter_btn)
        layout.addLayout(filter_row)

        # === Action buttons ===
        action_row = QHBoxLayout()

        self.scan_btn = QPushButton("Scan && indeksér")
        self.scan_btn.setStyleSheet("font-weight: bold;")
        self.scan_btn.clicked.connect(self.start_scan)
        action_row.addWidget(self.scan_btn)

        self.recursive_cb = QCheckBox("Inkl. undermapper")
        self.recursive_cb.setChecked(True)
        action_row.addWidget(self.recursive_cb)

        self.meta_btn = QPushButton("Udtræk metadata")
        self.meta_btn.clicked.connect(self.start_metadata_extraction)
        action_row.addWidget(self.meta_btn)

        self.hash_btn = QPushButton("Find dubletter")
        self.hash_btn.clicked.connect(self.start_hash_and_duplicates)
        action_row.addWidget(self.hash_btn)

        action_row.addStretch()

        self.export_csv_btn = QPushButton("Eksportér CSV")
        self.export_csv_btn.clicked.connect(self.do_export_csv)
        action_row.addWidget(self.export_csv_btn)

        self.export_html_btn = QPushButton("HTML-rapport")
        self.export_html_btn.clicked.connect(self.do_export_html)
        action_row.addWidget(self.export_html_btn)

        layout.addLayout(action_row)

        # === Progress bar ===
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        prog_row = QHBoxLayout()
        prog_row.addWidget(self.progress)
        prog_row.addWidget(self.progress_label)
        layout.addLayout(prog_row)

        # === Main splitter ===
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left: Tabs
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        left_layout.addWidget(self.tabs)

        # Tab 1: Results
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Filnavn", "Type", "Størrelse", "Ændret", "Status", "Advarsler", "Tags", "Sti"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.doubleClicked.connect(self._on_table_double_click)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.tabs.addTab(self.table, "Resultater")

        # Tab 2: Dashboard
        self.dashboard = QTextEdit()
        self.dashboard.setReadOnly(True)
        self.tabs.addTab(self.dashboard, "Dashboard")

        # Tab 3: Report
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.tabs.addTab(self.report, "Kvalitetsrapport")

        # Tab 4: Scan history
        self.scan_history = QTextEdit()
        self.scan_history.setReadOnly(True)
        self.tabs.addTab(self.scan_history, "Scan-historik")

        splitter.addWidget(left)

        # Right: Detail panel
        right = QWidget()
        right.setMinimumWidth(280)
        right.setMaximumWidth(400)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)

        # Preview
        pg = QGroupBox("Forhåndsvisning")
        pl = QVBoxLayout(pg)
        self.preview_label = QLabel("Vælg en fil")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(140)
        self.preview_label.setStyleSheet("background:#f5f5f5;border:1px solid #ddd;padding:4px;")
        pl.addWidget(self.preview_label)
        right_layout.addWidget(pg)

        # Metadata
        mg = QGroupBox("Metadata")
        ml = QVBoxLayout(mg)
        self.meta_text = QTextEdit()
        self.meta_text.setReadOnly(True)
        self.meta_text.setMaximumHeight(180)
        ml.addWidget(self.meta_text)
        right_layout.addWidget(mg)

        # Status changer
        sg = QGroupBox("Status")
        sl = QHBoxLayout(sg)
        self.status_combo = QComboBox()
        for s in STATUSES:
            self.status_combo.addItem(s)
        sl.addWidget(self.status_combo)
        set_status_btn = QPushButton("Sæt")
        set_status_btn.clicked.connect(self._set_status)
        sl.addWidget(set_status_btn)
        bulk_status_btn = QPushButton("Sæt alle valgte")
        bulk_status_btn.clicked.connect(self._bulk_set_status)
        sl.addWidget(bulk_status_btn)
        right_layout.addWidget(sg)

        # Tags
        tg = QGroupBox("Tags")
        tl = QVBoxLayout(tg)
        self.tag_display = QLabel("Ingen tags")
        tl.addWidget(self.tag_display)
        tr = QHBoxLayout()
        self.tag_combo = QComboBox()
        self.tag_combo.setEditable(True)
        self.tag_combo.setPlaceholderText("Skriv eller vælg tag...")
        tr.addWidget(self.tag_combo)
        add_btn = QPushButton("+")
        add_btn.setMaximumWidth(30)
        add_btn.clicked.connect(self._add_tag)
        tr.addWidget(add_btn)
        rm_btn = QPushButton("-")
        rm_btn.setMaximumWidth(30)
        rm_btn.clicked.connect(self._remove_tag)
        tr.addWidget(rm_btn)
        tl.addLayout(tr)

        # Quick tags
        qt_row = QHBoxLayout()
        for tag in ["ESDH-klar", "Konvertér", "Arkivér", "Slet"]:
            b = QPushButton(tag)
            b.setStyleSheet("font-size:10px;padding:2px 6px;")
            b.clicked.connect(self._make_quick_tagger(tag))
            qt_row.addWidget(b)
        tl.addLayout(qt_row)

        # Bulk tag
        bt_row = QHBoxLayout()
        bt_row.addWidget(QLabel("Bulk:"))
        self.bulk_tag_input = QLineEdit()
        self.bulk_tag_input.setPlaceholderText("Tag alle valgte...")
        bt_row.addWidget(self.bulk_tag_input)
        bulk_tag_btn = QPushButton("Tag valgte")
        bulk_tag_btn.clicked.connect(self._bulk_tag)
        bt_row.addWidget(bulk_tag_btn)
        tl.addLayout(bt_row)

        right_layout.addWidget(tg)
        right_layout.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([850, 300])

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Initialize
        self.dir_input.textChanged.connect(self._load_case_number)
        self._load_case_number()
        self._refresh_dashboard()
        self._refresh_tag_filter()

    # ===== Directory / Case =====

    def pick_directory(self):
        path = QFileDialog.getExistingDirectory(self, "Vælg mappe", self.dir_input.text())
        if path:
            self.dir_input.setText(path)

    def _load_case_number(self):
        d = self.dir_input.text().strip()
        self.case_input.setText(self.db.get_case_number(d) if d else "")

    def _save_case_number(self):
        d = self.dir_input.text().strip()
        c = self.case_input.text().strip()
        if d:
            self.db.set_case_number(d, c)
            self.status_bar.showMessage(f"Sagsnr. '{c}' gemt")

    # ===== Scanning =====

    def start_scan(self):
        directory = self.dir_input.text().strip()
        if not directory:
            return

        ext_text = self.ext_input.text().strip()
        extensions = [e.strip() for e in ext_text.split(",") if e.strip()] if ext_text else None

        self.scan_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress.setValue(0)

        worker = BatchIndexer(self.db, directory, self.recursive_cb.isChecked(), extensions)
        worker.progress.connect(self._on_scan_progress)
        worker.finished.connect(self._on_scan_done)
        worker.start()
        self._workers.append(worker)

    def _on_scan_progress(self, current, total, filename):
        self.progress.setMaximum(total)
        self.progress.setValue(current)
        self.progress_label.setText(f"{current}/{total} – {filename}")

    def _on_scan_done(self, stats):
        self.scan_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.progress_label.setVisible(False)
        self.status_bar.showMessage(
            f"Scan færdig: {stats['total']} filer – "
            f"{stats['new']} nye, {stats['updated']} opdaterede, "
            f"{stats['unchanged']} uændrede, {stats['errors']} fejl"
        )
        self.refresh_table()
        self._refresh_dashboard()
        self._refresh_scan_history()
        self._refresh_tag_filter()

    # ===== Metadata extraction =====

    def start_metadata_extraction(self):
        self.meta_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress.setValue(0)

        worker = BatchMetadataExtractor(self.db)
        worker.progress.connect(self._on_scan_progress)
        worker.finished.connect(self._on_meta_done)
        worker.start()
        self._workers.append(worker)

    def _on_meta_done(self, count):
        self.meta_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.progress_label.setVisible(False)
        self.status_bar.showMessage(f"Metadata udtrukket for {count} filer")
        self._refresh_dashboard()

    # ===== Hashing / Duplicates =====

    def start_hash_and_duplicates(self):
        self.hash_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress.setValue(0)

        worker = BatchHasher(self.db)
        worker.progress.connect(self._on_scan_progress)
        worker.finished.connect(self._on_hash_done)
        worker.start()
        self._workers.append(worker)

    def _on_hash_done(self, count):
        self.hash_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.progress_label.setVisible(False)

        dups = self.db.find_duplicates()
        total_dup = sum(len(g) for g in dups)
        self.status_bar.showMessage(
            f"Hash beregnet for {count} filer – {total_dup} dubletter i {len(dups)} grupper"
        )
        self._refresh_dashboard()

        # Highlight duplicates in table
        dup_paths = set()
        for g in dups:
            for f in g:
                dup_paths.add(f["path"])
        for row in range(self.table.rowCount()):
            pi = self.table.item(row, 7)
            if pi and pi.text() in dup_paths:
                for col in range(8):
                    item = self.table.item(row, col)
                    if item:
                        item.setBackground(DUP_COLOR)

    # ===== Table =====

    def refresh_table(self):
        query = self.search_input.text().strip()
        ext = self.ext_input.text().strip()
        status = self.status_filter.currentData()
        tag = self.tag_filter.currentData()
        has_warnings = True if self.warn_cb.isChecked() else None

        filters = {}
        if query:
            filters["query"] = query
        if ext:
            filters["ext"] = ext
        if status:
            filters["status"] = status
        if tag:
            filters["tag"] = tag
        if has_warnings:
            filters["has_warnings"] = has_warnings

        files = self.db.search(**filters)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        for f in files:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(f["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(f["ext"]))

            si = QTableWidgetItem(format_size(f["size"]))
            si.setData(Qt.ItemDataRole.UserRole, f["size"])
            self.table.setItem(row, 2, si)

            self.table.setItem(row, 3, QTableWidgetItem(f["modified"]))
            self.table.setItem(row, 4, QTableWidgetItem(f.get("status", "")))

            warnings = f.get("warnings", [])
            self.table.setItem(row, 5, QTableWidgetItem("; ".join(warnings)))

            tags = f.get("tags", [])
            self.table.setItem(row, 6, QTableWidgetItem(", ".join(tags)))

            self.table.setItem(row, 7, QTableWidgetItem(f["path"]))

            if warnings:
                for col in range(8):
                    item = self.table.item(row, col)
                    if item:
                        item.setBackground(WARN_COLOR)

        self.table.setSortingEnabled(True)
        self.status_bar.showMessage(f"Viser {len(files)} filer")

    # ===== Selection / Preview =====

    def _selected_paths(self) -> list[str]:
        paths = []
        for idx in self.table.selectionModel().selectedRows():
            item = self.table.item(idx.row(), 7)
            if item:
                paths.append(item.text())
        return paths

    def _on_selection_changed(self):
        paths = self._selected_paths()
        if not paths:
            return
        path = paths[0]

        # Preview
        ext = os.path.splitext(path)[1].lower()
        img_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".ico", ".webp"}
        if ext in img_exts:
            px = QPixmap(path)
            if not px.isNull():
                self.preview_label.setPixmap(
                    px.scaled(self.preview_label.width() - 10, 140,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )
            else:
                self.preview_label.setText("Kan ikke vise")
        else:
            self.preview_label.setText(os.path.basename(path))

        # Metadata from DB
        f = self.db.get_file(path)
        if f:
            meta = f.get("metadata", {})
            if meta:
                lines = [f"<b>{k}:</b> {v}" for k, v in meta.items()]
                self.meta_text.setHtml("<br>".join(lines))
            elif not f.get("metadata_extracted"):
                self.meta_text.setPlainText("Metadata ikke udtrukket endnu.\nKlik 'Udtræk metadata'.")
            else:
                self.meta_text.setPlainText("Ingen metadata")

            # Status
            idx = self.status_combo.findText(f.get("status", "ny"))
            if idx >= 0:
                self.status_combo.setCurrentIndex(idx)

        # Tags
        self._refresh_tag_display(path)

    def _refresh_tag_display(self, path: str):
        tags = self.db.get_tags(path)
        self.tag_display.setText(", ".join(tags) if tags else "Ingen tags")
        self.tag_combo.clear()
        self.tag_combo.addItems(self.db.all_tags())

    # ===== Status =====

    def _set_status(self):
        paths = self._selected_paths()
        if not paths:
            return
        status = self.status_combo.currentText()
        self.db.set_status(paths[0], status)
        self.db.commit()
        self.refresh_table()

    def _bulk_set_status(self):
        paths = self._selected_paths()
        if not paths:
            return
        status = self.status_combo.currentText()
        self.db.bulk_set_status(paths, status)
        self.refresh_table()
        self.status_bar.showMessage(f"Status '{status}' sat på {len(paths)} filer")

    # ===== Tags =====

    def _add_tag(self):
        paths = self._selected_paths()
        tag = self.tag_combo.currentText().strip()
        if paths and tag:
            self.db.add_tag(paths[0], tag)
            self._refresh_tag_display(paths[0])
            self._refresh_tag_filter()

    def _remove_tag(self):
        paths = self._selected_paths()
        tag = self.tag_combo.currentText().strip()
        if paths and tag:
            self.db.remove_tag(paths[0], tag)
            self._refresh_tag_display(paths[0])
            self._refresh_tag_filter()

    def _make_quick_tagger(self, tag):
        def handler():
            paths = self._selected_paths()
            if paths:
                self.db.add_tag(paths[0], tag)
                self._refresh_tag_display(paths[0])
                self._refresh_tag_filter()
        return handler

    def _bulk_tag(self):
        paths = self._selected_paths()
        tag = self.bulk_tag_input.text().strip()
        if paths and tag:
            self.db.bulk_add_tag(paths, tag)
            self.bulk_tag_input.clear()
            self.refresh_table()
            self._refresh_tag_filter()
            self.status_bar.showMessage(f"Tag '{tag}' tilføjet til {len(paths)} filer")

    def _refresh_tag_filter(self):
        current = self.tag_filter.currentData()
        self.tag_filter.clear()
        self.tag_filter.addItem("(alle)", "")
        for tag in self.db.all_tags():
            self.tag_filter.addItem(tag, tag)
        if current:
            idx = self.tag_filter.findData(current)
            if idx >= 0:
                self.tag_filter.setCurrentIndex(idx)

    # ===== Dashboard =====

    def _refresh_dashboard(self):
        stats = self.db.get_stats()
        html = generate_html_report(self.db)
        self.dashboard.setHtml(html)

    def _refresh_scan_history(self):
        history = self.db.get_scan_history()
        if not history:
            self.scan_history.setHtml("<p>Ingen scanninger endnu.</p>")
            return
        lines = ["<h2>Scan-historik</h2>",
                  "<table border='1' cellpadding='4' cellspacing='0'>",
                  "<tr><th>Tidspunkt</th><th>Mappe</th><th>Filer</th><th>Nye</th><th>Opdaterede</th><th>Uændrede</th></tr>"]
        for s in history:
            lines.append(
                f"<tr><td>{s['started_at'][:16]}</td><td>{s['scan_root']}</td>"
                f"<td>{s['files_found']}</td><td>{s['files_new']}</td>"
                f"<td>{s['files_updated']}</td><td>{s['files_unchanged']}</td></tr>"
            )
        lines.append("</table>")
        self.scan_history.setHtml("\n".join(lines))

    # ===== Export =====

    def do_export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Gem CSV", "esdh_filscan.csv", "CSV (*.csv)"
        )
        if not path:
            return

        filters = {}
        q = self.search_input.text().strip()
        if q:
            filters["query"] = q
        ext = self.ext_input.text().strip()
        if ext:
            filters["ext"] = ext
        status = self.status_filter.currentData()
        if status:
            filters["status"] = status
        tag = self.tag_filter.currentData()
        if tag:
            filters["tag"] = tag

        count = export_csv(self.db, path, filters, include_metadata=True)
        self.status_bar.showMessage(f"Eksporteret {count} filer til {path}")

    def do_export_html(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Gem HTML-rapport", "esdh_rapport.html", "HTML (*.html)"
        )
        if not path:
            return
        export_html_report(self.db, path)
        self.status_bar.showMessage(f"Rapport gemt: {path}")

    # ===== Open file =====

    def _on_table_double_click(self, index):
        row = index.row()
        item = self.table.item(row, 7)
        if not item:
            return
        path = item.text()
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
