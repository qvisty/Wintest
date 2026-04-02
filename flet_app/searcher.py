"""File search logic running in a background thread."""

import os
from pathlib import Path
from threading import Thread


class FileSearcher:
    def __init__(self, directory: str, query: str, on_result, on_done, recursive: bool = True):
        self.directory = directory
        self.query = query.lower()
        self.on_result = on_result
        self.on_done = on_done
        self.recursive = recursive
        self._stopped = False
        self._thread = Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stopped = True

    def _run(self):
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
                            self.on_result(full_path)
                            count += 1
            else:
                for name in os.listdir(self.directory):
                    if self._stopped:
                        break
                    full_path = str(Path(self.directory) / name)
                    if os.path.isfile(full_path) and self.query in name.lower():
                        self.on_result(full_path)
                        count += 1
        except PermissionError:
            pass
        self.on_done(count)
