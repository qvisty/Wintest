"""Persistent SQLite database for file indexing.

Stores file info, metadata, tags, case numbers, and processing status
so 3000+ files don't need to be re-scanned every time.
"""

import json
import os
import sqlite3
from datetime import datetime


DB_DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".filesearch_index.db")


class FileIndex:
    def __init__(self, db_path: str = DB_DEFAULT_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                ext TEXT,
                size INTEGER,
                modified TEXT,
                scan_root TEXT,
                indexed_at TEXT NOT NULL,
                warnings TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                metadata_extracted INTEGER DEFAULT 0,
                file_hash TEXT,
                status TEXT DEFAULT 'ny'
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                added_at TEXT NOT NULL,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                UNIQUE(file_id, tag)
            );

            CREATE TABLE IF NOT EXISTS case_numbers (
                folder_path TEXT PRIMARY KEY,
                case_number TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scan_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_root TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                files_found INTEGER DEFAULT 0,
                files_new INTEGER DEFAULT 0,
                files_updated INTEGER DEFAULT 0,
                files_unchanged INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
            CREATE INDEX IF NOT EXISTS idx_files_ext ON files(ext);
            CREATE INDEX IF NOT EXISTS idx_files_scan_root ON files(scan_root);
            CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
            CREATE INDEX IF NOT EXISTS idx_files_hash ON files(file_hash);
            CREATE INDEX IF NOT EXISTS idx_tags_file ON tags(file_id);
            CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
        """)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- File indexing ---

    def upsert_file(self, path: str, name: str, ext: str, size: int,
                    modified: str, scan_root: str, warnings: list) -> str:
        """Insert or update a file. Returns 'new', 'updated', or 'unchanged'."""
        now = datetime.now().isoformat()
        existing = self.conn.execute(
            "SELECT id, size, modified FROM files WHERE path = ?", (path,)
        ).fetchone()

        if existing is None:
            self.conn.execute(
                """INSERT INTO files (path, name, ext, size, modified, scan_root, indexed_at, warnings)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (path, name, ext, size, modified, scan_root, now, json.dumps(warnings))
            )
            return "new"
        elif existing["size"] != size or existing["modified"] != modified:
            self.conn.execute(
                """UPDATE files SET name=?, ext=?, size=?, modified=?, scan_root=?,
                   indexed_at=?, warnings=?, metadata_extracted=0, file_hash=NULL
                   WHERE path=?""",
                (name, ext, size, modified, scan_root, now, json.dumps(warnings), path)
            )
            return "updated"
        else:
            return "unchanged"

    def commit(self):
        self.conn.commit()

    def set_file_hash(self, path: str, file_hash: str):
        self.conn.execute("UPDATE files SET file_hash = ? WHERE path = ?", (file_hash, path))

    def set_metadata(self, path: str, metadata: dict):
        self.conn.execute(
            "UPDATE files SET metadata = ?, metadata_extracted = 1 WHERE path = ?",
            (json.dumps(metadata, ensure_ascii=False), path)
        )

    def set_status(self, path: str, status: str):
        self.conn.execute("UPDATE files SET status = ? WHERE path = ?", (status, path))

    def bulk_set_status(self, paths: list[str], status: str):
        self.conn.executemany(
            "UPDATE files SET status = ? WHERE path = ?",
            [(status, p) for p in paths]
        )
        self.conn.commit()

    # --- Querying ---

    def get_file(self, path: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
        return self._row_to_dict(row) if row else None

    def search(self, query: str = "", ext: str = "", status: str = "",
               tag: str = "", scan_root: str = "",
               has_warnings: bool | None = None,
               limit: int = 5000, offset: int = 0) -> list[dict]:
        """Flexible search across the index."""
        conditions = []
        params = []

        if query:
            conditions.append("f.name LIKE ?")
            params.append(f"%{query}%")
        if ext:
            exts = [e.strip().lower().lstrip(".") for e in ext.split(",") if e.strip()]
            placeholders = ",".join("?" for _ in exts)
            conditions.append(f"REPLACE(f.ext, '.', '') IN ({placeholders})")
            params.extend(exts)
        if status:
            conditions.append("f.status = ?")
            params.append(status)
        if scan_root:
            conditions.append("f.scan_root = ?")
            params.append(scan_root)
        if has_warnings is True:
            conditions.append("f.warnings != '[]'")
        elif has_warnings is False:
            conditions.append("f.warnings = '[]'")
        if tag:
            conditions.append("EXISTS (SELECT 1 FROM tags t WHERE t.file_id = f.id AND t.tag = ?)")
            params.append(tag)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT f.* FROM files f {where} ORDER BY f.name LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count(self, **kwargs) -> int:
        """Count files matching search criteria."""
        # Reuse search logic but just count
        results = self.search(**kwargs, limit=999999)
        return len(results)

    def get_stats(self) -> dict:
        """Get overall index statistics."""
        stats = {}
        stats["total_files"] = self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        stats["total_size"] = self.conn.execute("SELECT COALESCE(SUM(size), 0) FROM files").fetchone()[0]
        stats["metadata_extracted"] = self.conn.execute(
            "SELECT COUNT(*) FROM files WHERE metadata_extracted = 1"
        ).fetchone()[0]
        stats["with_warnings"] = self.conn.execute(
            "SELECT COUNT(*) FROM files WHERE warnings != '[]'"
        ).fetchone()[0]
        stats["with_tags"] = self.conn.execute(
            "SELECT COUNT(DISTINCT file_id) FROM tags"
        ).fetchone()[0]

        # Status breakdown
        statuses = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM files GROUP BY status ORDER BY cnt DESC"
        ).fetchall()
        stats["by_status"] = {r["status"]: r["cnt"] for r in statuses}

        # Extension breakdown
        exts = self.conn.execute(
            "SELECT ext, COUNT(*) as cnt, SUM(size) as total_size FROM files GROUP BY ext ORDER BY cnt DESC"
        ).fetchall()
        stats["by_ext"] = [{"ext": r["ext"], "count": r["cnt"], "size": r["total_size"]} for r in exts]

        # Tag breakdown
        tag_counts = self.conn.execute(
            "SELECT tag, COUNT(*) as cnt FROM tags GROUP BY tag ORDER BY cnt DESC"
        ).fetchall()
        stats["by_tag"] = {r["tag"]: r["cnt"] for r in tag_counts}

        # Scan roots
        roots = self.conn.execute(
            "SELECT scan_root, COUNT(*) as cnt FROM files GROUP BY scan_root ORDER BY cnt DESC"
        ).fetchall()
        stats["by_scan_root"] = {r["scan_root"]: r["cnt"] for r in roots}

        return stats

    def find_duplicates(self) -> list[list[dict]]:
        """Find files with same hash (must have been hashed first)."""
        groups = self.conn.execute(
            """SELECT file_hash, COUNT(*) as cnt FROM files
               WHERE file_hash IS NOT NULL AND file_hash != ''
               GROUP BY file_hash HAVING cnt > 1"""
        ).fetchall()

        result = []
        for g in groups:
            files = self.conn.execute(
                "SELECT * FROM files WHERE file_hash = ?", (g["file_hash"],)
            ).fetchall()
            result.append([self._row_to_dict(f) for f in files])
        return result

    def files_needing_metadata(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM files WHERE metadata_extracted = 0 LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def files_needing_hash(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM files WHERE file_hash IS NULL AND size > 0 LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # --- Tags ---

    def add_tag(self, path: str, tag: str):
        file_id = self._get_file_id(path)
        if file_id is None:
            return
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO tags (file_id, tag, added_at) VALUES (?, ?, ?)",
            (file_id, tag, now)
        )
        self.conn.commit()

    def remove_tag(self, path: str, tag: str):
        file_id = self._get_file_id(path)
        if file_id is None:
            return
        self.conn.execute("DELETE FROM tags WHERE file_id = ? AND tag = ?", (file_id, tag))
        self.conn.commit()

    def get_tags(self, path: str) -> list[str]:
        file_id = self._get_file_id(path)
        if file_id is None:
            return []
        rows = self.conn.execute(
            "SELECT tag FROM tags WHERE file_id = ? ORDER BY tag", (file_id,)
        ).fetchall()
        return [r["tag"] for r in rows]

    def bulk_add_tag(self, paths: list[str], tag: str):
        now = datetime.now().isoformat()
        for path in paths:
            file_id = self._get_file_id(path)
            if file_id is not None:
                self.conn.execute(
                    "INSERT OR IGNORE INTO tags (file_id, tag, added_at) VALUES (?, ?, ?)",
                    (file_id, tag, now)
                )
        self.conn.commit()

    def all_tags(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT tag FROM tags ORDER BY tag").fetchall()
        return [r["tag"] for r in rows]

    # --- Case numbers ---

    def set_case_number(self, folder: str, case_number: str):
        folder = os.path.normpath(folder)
        if case_number:
            self.conn.execute(
                "INSERT OR REPLACE INTO case_numbers (folder_path, case_number) VALUES (?, ?)",
                (folder, case_number)
            )
        else:
            self.conn.execute("DELETE FROM case_numbers WHERE folder_path = ?", (folder,))
        self.conn.commit()

    def get_case_number(self, folder: str) -> str:
        folder = os.path.normpath(folder)
        row = self.conn.execute(
            "SELECT case_number FROM case_numbers WHERE folder_path = ?", (folder,)
        ).fetchone()
        if row:
            return row["case_number"]
        # Check parents
        parts = folder.split(os.sep)
        for i in range(len(parts) - 1, 0, -1):
            parent = os.sep.join(parts[:i])
            row = self.conn.execute(
                "SELECT case_number FROM case_numbers WHERE folder_path = ?", (parent,)
            ).fetchone()
            if row:
                return row["case_number"]
        return ""

    def get_all_case_mappings(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT * FROM case_numbers ORDER BY folder_path").fetchall()
        return {r["folder_path"]: r["case_number"] for r in rows}

    # --- Scan log ---

    def start_scan(self, scan_root: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO scan_log (scan_root, started_at) VALUES (?, ?)",
            (scan_root, datetime.now().isoformat())
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_scan(self, scan_id: int, found: int, new: int, updated: int, unchanged: int):
        self.conn.execute(
            """UPDATE scan_log SET finished_at=?, files_found=?, files_new=?,
               files_updated=?, files_unchanged=? WHERE id=?""",
            (datetime.now().isoformat(), found, new, updated, unchanged, scan_id)
        )
        self.conn.commit()

    def get_scan_history(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM scan_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Helpers ---

    def _get_file_id(self, path: str) -> int | None:
        row = self.conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()
        return row["id"] if row else None

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        d["warnings"] = json.loads(d.get("warnings") or "[]")
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        d["tags"] = self.get_tags(d["path"])
        return d
