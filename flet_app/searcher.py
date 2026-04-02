"""File search logic running in a background thread."""

import os
from datetime import datetime
from pathlib import Path
from threading import Thread
from validator import validate_file


class FileSearcher:
    def __init__(self, directory: str, query: str, on_result, on_done,
                 recursive: bool = True, extensions: list = None):
        self.directory = directory
        self.query = query.lower()
        self.on_result = on_result
        self.on_done = on_done
        self.recursive = recursive
        self.extensions = [e.lower().lstrip(".") for e in extensions] if extensions else None
        self._stopped = False
        self._thread = Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stopped = True

    def _match(self, name: str) -> bool:
        if self.query and self.query not in name.lower():
            return False
        if self.extensions:
            ext = Path(name).suffix.lower().lstrip(".")
            if ext not in self.extensions:
                return False
        return True

    def _file_info(self, full_path: str) -> dict:
        stat = os.stat(full_path)
        info = {
            "name": os.path.basename(full_path),
            "path": full_path,
            "ext": Path(full_path).suffix.lower(),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        }
        info["warnings"] = validate_file(info)
        return info

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
                        if self._match(name):
                            full_path = str(Path(root) / name)
                            try:
                                self.on_result(self._file_info(full_path))
                                count += 1
                            except OSError:
                                pass
            else:
                for name in os.listdir(self.directory):
                    if self._stopped:
                        break
                    full_path = str(Path(self.directory) / name)
                    if os.path.isfile(full_path) and self._match(name):
                        try:
                            self.on_result(self._file_info(full_path))
                            count += 1
                        except OSError:
                            pass
        except PermissionError:
            pass
        self.on_done(count)
