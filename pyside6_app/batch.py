"""Batch processor for indexing, metadata extraction, and hashing.

Designed to handle 3000+ files with progress reporting.
Runs operations in background threads with callbacks for UI updates.
"""

import os
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from database import FileIndex
from validator import validate_file, compute_file_hash
from metadata import extract_metadata


class BatchIndexer(QThread):
    """Scan a directory and index all files into the database."""
    progress = Signal(int, int, str)  # current, total, current_file
    file_indexed = Signal(dict)       # file info dict
    finished = Signal(dict)           # summary stats

    def __init__(self, db: FileIndex, directory: str, recursive: bool = True,
                 extensions: list = None):
        super().__init__()
        self.db = db
        self.directory = directory
        self.recursive = recursive
        self.extensions = [e.lower().lstrip(".") for e in extensions] if extensions else None
        self._stopped = False

    def stop(self):
        self._stopped = True

    def _match_ext(self, name: str) -> bool:
        if not self.extensions:
            return True
        ext = Path(name).suffix.lower().lstrip(".")
        return ext in self.extensions

    def run(self):
        # Phase 1: Collect all file paths
        all_files = []
        try:
            if self.recursive:
                for root, dirs, files in os.walk(self.directory):
                    if self._stopped:
                        break
                    for name in files:
                        if self._match_ext(name):
                            all_files.append(str(Path(root) / name))
            else:
                for name in os.listdir(self.directory):
                    full = str(Path(self.directory) / name)
                    if os.path.isfile(full) and self._match_ext(name):
                        all_files.append(full)
        except PermissionError:
            pass

        total = len(all_files)
        scan_id = self.db.start_scan(self.directory)
        stats = {"new": 0, "updated": 0, "unchanged": 0, "errors": 0}

        # Phase 2: Index each file
        for i, filepath in enumerate(all_files):
            if self._stopped:
                break

            self.progress.emit(i + 1, total, os.path.basename(filepath))

            try:
                stat = os.stat(filepath)
                name = os.path.basename(filepath)
                ext = Path(filepath).suffix.lower()
                size = stat.st_size
                modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")

                info = {
                    "name": name, "path": filepath, "ext": ext,
                    "size": size, "modified": modified,
                }
                warnings = validate_file(info)
                info["warnings"] = warnings

                result = self.db.upsert_file(
                    filepath, name, ext, size, modified, self.directory, warnings
                )
                stats[result] = stats.get(result, 0) + 1

                if result in ("new", "updated"):
                    self.file_indexed.emit(info)

                # Commit every 100 files for performance
                if (i + 1) % 100 == 0:
                    self.db.commit()

            except (OSError, PermissionError):
                stats["errors"] += 1

        self.db.commit()
        self.db.finish_scan(scan_id, total, stats["new"], stats["updated"], stats["unchanged"])
        stats["total"] = total
        self.finished.emit(stats)


class BatchMetadataExtractor(QThread):
    """Extract metadata for all files that haven't been processed yet."""
    progress = Signal(int, int, str)
    finished = Signal(int)

    def __init__(self, db: FileIndex, batch_size: int = 0):
        super().__init__()
        self.db = db
        self.batch_size = batch_size
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        limit = self.batch_size if self.batch_size > 0 else 999999
        files = self.db.files_needing_metadata(limit)
        total = len(files)
        processed = 0

        for i, f in enumerate(files):
            if self._stopped:
                break

            self.progress.emit(i + 1, total, f["name"])

            try:
                meta = extract_metadata(f["path"])
                self.db.set_metadata(f["path"], meta)
                processed += 1
            except Exception:
                self.db.set_metadata(f["path"], {"error": "Kunne ikke udtrække metadata"})

            if (i + 1) % 50 == 0:
                self.db.commit()

        self.db.commit()
        self.finished.emit(processed)


class BatchHasher(QThread):
    """Compute file hashes for duplicate detection."""
    progress = Signal(int, int, str)
    finished = Signal(int)

    def __init__(self, db: FileIndex, batch_size: int = 0):
        super().__init__()
        self.db = db
        self.batch_size = batch_size
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        limit = self.batch_size if self.batch_size > 0 else 999999
        files = self.db.files_needing_hash(limit)
        total = len(files)
        processed = 0

        for i, f in enumerate(files):
            if self._stopped:
                break

            self.progress.emit(i + 1, total, f["name"])

            file_hash = compute_file_hash(f["path"])
            if file_hash:
                self.db.set_file_hash(f["path"], file_hash)
                processed += 1

            if (i + 1) % 50 == 0:
                self.db.commit()

        self.db.commit()
        self.finished.emit(processed)
