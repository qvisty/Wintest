"""Main window UI for PySide6 file search app."""

import csv
import os
import subprocess
import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QFileDialog, QStatusBar,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt
from searcher import FileSearcher

COMMON_EXTENSIONS = ["pdf", "docx", "xlsx", "msg", "doc", "xls", "ppt", "pptx", "txt", "csv", "jpg", "png"]


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Search (PySide6)")
        self.resize(1000, 650)
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
        # Quick-select buttons
        for ext in ["pdf", "docx", "xlsx", "msg"]:
            btn = QPushButton(f".{ext}")
            btn.setCheckable(True)
            btn.setMaximumWidth(60)
            btn.clicked.connect(self._make_ext_toggler(ext))
            filter_row.addWidget(btn)
        layout.addLayout(filter_row)

        # Results table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Filnavn", "Type", "Størrelse", "Ændret", "Sti"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._on_table_double_click)
        layout.addWidget(self.table)

        # Bottom row: export button + status
        bottom_row = QHBoxLayout()
        self.export_btn = QPushButton("Eksportér til CSV...")
        self.export_btn.clicked.connect(self.export_csv)
        self.export_btn.setEnabled(False)
        bottom_row.addWidget(self.export_btn)
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

        # Stop any running search
        if self.searcher and self.searcher.isRunning():
            self.searcher.stop()
            self.searcher.wait()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._results_data = []
        self.search_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
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
        self.table.setItem(row, 4, QTableWidgetItem(info["path"]))

    def on_search_done(self, count: int):
        self.search_btn.setEnabled(True)
        self.export_btn.setEnabled(count > 0)
        self.table.setSortingEnabled(True)

        total_size = sum(r["size"] for r in self._results_data)
        self.status.showMessage(f"Fandt {count} fil(er) – samlet størrelse: {format_size(total_size)}")

    def _on_table_double_click(self, index):
        row = index.row()
        path_item = self.table.item(row, 4)
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
            writer.writerow(["Filnavn", "Type", "Størrelse (bytes)", "Ændret", "Fuld sti"])
            for info in self._results_data:
                writer.writerow([info["name"], info["ext"], info["size"], info["modified"], info["path"]])

        self.status.showMessage(f"Eksporteret {len(self._results_data)} rækker til {path}")
