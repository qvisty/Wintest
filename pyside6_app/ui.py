"""Main window UI for PySide6 file search app."""

import os
import subprocess
import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QListWidget, QFileDialog, QStatusBar,
    QCheckBox,
)
from PySide6.QtCore import Qt
from searcher import FileSearcher


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Search (PySide6)")
        self.resize(800, 600)
        self.searcher = None

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
        self.search_input.setPlaceholderText("Skriv filnavn eller del af filnavn...")
        self.search_input.returnPressed.connect(self.start_search)
        search_row.addWidget(self.search_input)
        self.recursive_cb = QCheckBox("Inkl. undermapper")
        self.recursive_cb.setChecked(True)
        search_row.addWidget(self.recursive_cb)
        self.search_btn = QPushButton("Søg")
        self.search_btn.clicked.connect(self.start_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        # Results list
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(self.open_file_location)
        layout.addWidget(self.results)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Klar.")

    def pick_directory(self):
        path = QFileDialog.getExistingDirectory(self, "Vælg mappe", self.dir_input.text())
        if path:
            self.dir_input.setText(path)

    def start_search(self):
        query = self.search_input.text().strip()
        directory = self.dir_input.text().strip()
        if not query or not directory:
            return

        # Stop any running search
        if self.searcher and self.searcher.isRunning():
            self.searcher.stop()
            self.searcher.wait()

        self.results.clear()
        self.search_btn.setEnabled(False)
        self.status.showMessage("Søger...")

        self.searcher = FileSearcher(directory, query, self.recursive_cb.isChecked())
        self.searcher.result_found.connect(self.add_result)
        self.searcher.search_done.connect(self.on_search_done)
        self.searcher.start()

    def add_result(self, path: str):
        self.results.addItem(path)

    def on_search_done(self, count: int):
        self.search_btn.setEnabled(True)
        self.status.showMessage(f"Fandt {count} fil(er).")

    def open_file_location(self, item):
        path = item.text()
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
