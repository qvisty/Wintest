"""File search logic running in a background thread."""

import os
from pathlib import Path
from PySide6.QtCore import QThread, Signal


class FileSearcher(QThread):
    result_found = Signal(str)
    search_done = Signal(int)

    def __init__(self, directory: str, query: str, recursive: bool = True):
        super().__init__()
        self.directory = directory
        self.query = query.lower()
        self.recursive = recursive
        self._stopped = False

    def run(self):
        count = 0
        try:
            if self.recursive:
                for root, dirs, files in os.walk(self.directory):
                    if self._stopped:
                        break
                    for name in files:
                        if self._stopped:
                            break
                        if self.query in name.lower():
                            full_path = str(Path(root) / name)
                            self.result_found.emit(full_path)
                            count += 1
            else:
                for name in os.listdir(self.directory):
                    if self._stopped:
                        break
                    full_path = str(Path(self.directory) / name)
                    if os.path.isfile(full_path) and self.query in name.lower():
                        self.result_found.emit(full_path)
                        count += 1
        except PermissionError:
            pass
        self.search_done.emit(count)

    def stop(self):
        self._stopped = True
