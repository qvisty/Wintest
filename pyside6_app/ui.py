"""Main window UI for PySide6 file search app."""

import csv
import os
import subprocess
import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QFileDialog, QStatusBar,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTabWidget, QTextEdit,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from searcher import FileSearcher
from validator import find_duplicates, format_size

WARN_COLOR = QColor(255, 240, 220)
DUPLICATE_COLOR = QColor(255, 220, 220)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESDH File Scanner (PySide6)")
        self.resize(1100, 700)
        self.searcher = None
        self._results_data = []

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

        # Tabs: Results + Quality Report
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tab 1: Results table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Filnavn", "Type", "Størrelse", "Ændret", "Advarsler", "Sti"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._on_table_double_click)
        self.tabs.addTab(self.table, "Resultater")

        # Tab 2: Quality report
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.tabs.addTab(self.report, "Kvalitetsrapport")

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

    def pick_directory(self):
        path = QFileDialog.getExistingDirectory(self, "Vælg mappe", self.dir_input.text())
        if path:
            self.dir_input.setText(path)

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

        self.table.setItem(row, 5, QTableWidgetItem(info["path"]))

        # Highlight rows with warnings
        if warnings:
            for col in range(6):
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

    def _generate_report(self):
        """Generate the quality report tab content."""
        lines = ["<h2>Kvalitetsrapport</h2>"]
        data = self._results_data

        # Summary
        total = len(data)
        total_size = sum(r["size"] for r in data)
        lines.append(f"<p><b>Samlet:</b> {total} filer, {format_size(total_size)}</p>")

        # File types breakdown
        ext_counts = {}
        for r in data:
            ext = r["ext"] or "(ingen)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
        lines.append("<h3>Filtyper</h3><ul>")
        for ext, cnt in sorted(ext_counts.items(), key=lambda x: -x[1]):
            lines.append(f"<li><b>{ext}</b>: {cnt} filer</li>")
        lines.append("</ul>")

        # Warnings summary
        warn_files = [r for r in data if r.get("warnings")]
        if warn_files:
            lines.append(f"<h3>Advarsler ({len(warn_files)} filer)</h3>")

            # Group by warning type
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

    def run_duplicate_check(self):
        self.status.showMessage("Søger efter dubletter (beregner hash)...")
        self.dup_btn.setEnabled(False)

        # Run in background thread to avoid freezing UI
        from PySide6.QtCore import QThread, Signal

        class DupWorker(QThread):
            done = Signal(dict)

            def __init__(self, results):
                super().__init__()
                self.results = results

            def run(self):
                duplicates = find_duplicates(self.results)
                self.done.emit(duplicates)

        def on_dup_done(duplicates):
            self.dup_btn.setEnabled(True)

            # Mark duplicate rows in table
            dup_paths = set()
            for group in duplicates.values():
                for f in group:
                    dup_paths.add(f["path"])

            for row in range(self.table.rowCount()):
                path_item = self.table.item(row, 5)
                if path_item and path_item.text() in dup_paths:
                    for col in range(6):
                        item = self.table.item(row, col)
                        if item:
                            item.setBackground(DUPLICATE_COLOR)

            # Add to report
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

    def _on_table_double_click(self, index):
        row = index.row()
        path_item = self.table.item(row, 5)
        if not path_item:
            return
        path = path_item.text()
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Gem CSV-fil", "filsøgning.csv", "CSV-filer (*.csv)"
        )
        if not path:
            return

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Filnavn", "Type", "Størrelse (bytes)", "Ændret", "Advarsler", "Fuld sti"])
            for info in self._results_data:
                warnings = "; ".join(info.get("warnings", []))
                writer.writerow([info["name"], info["ext"], info["size"], info["modified"], warnings, info["path"]])

        self.status.showMessage(f"Eksporteret {len(self._results_data)} rækker til {path}")
