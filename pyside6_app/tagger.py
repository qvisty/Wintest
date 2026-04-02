"""File tagging and folder-to-case-number mapping.

Tags and mappings are persisted in a JSON file so they survive between sessions.
"""

import json
import os

DEFAULT_STORE = os.path.join(os.path.expanduser("~"), ".filesearch_tags.json")


class TagStore:
    def __init__(self, path: str = DEFAULT_STORE):
        self.path = path
        self._data = {"tags": {}, "folder_cases": {}}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        # Ensure keys exist
        self._data.setdefault("tags", {})
        self._data.setdefault("folder_cases", {})

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    # --- File tags ---

    def get_tags(self, file_path: str) -> list[str]:
        return self._data["tags"].get(file_path, [])

    def add_tag(self, file_path: str, tag: str):
        tags = self._data["tags"].setdefault(file_path, [])
        if tag not in tags:
            tags.append(tag)
            self._save()

    def remove_tag(self, file_path: str, tag: str):
        tags = self._data["tags"].get(file_path, [])
        if tag in tags:
            tags.remove(tag)
            if not tags:
                del self._data["tags"][file_path]
            self._save()

    def set_tags(self, file_path: str, tags: list[str]):
        if tags:
            self._data["tags"][file_path] = tags
        elif file_path in self._data["tags"]:
            del self._data["tags"][file_path]
        self._save()

    def all_tags(self) -> list[str]:
        """Return all unique tags used across all files."""
        seen = set()
        for tags in self._data["tags"].values():
            seen.update(tags)
        return sorted(seen)

    # --- Folder-to-case mappings ---

    def get_case_number(self, folder_path: str) -> str:
        """Get case number for a folder. Checks exact match, then parents."""
        normalized = os.path.normpath(folder_path)
        # Check exact match first
        if normalized in self._data["folder_cases"]:
            return self._data["folder_cases"][normalized]
        # Check parent folders
        parts = normalized.split(os.sep)
        for i in range(len(parts) - 1, 0, -1):
            parent = os.sep.join(parts[:i])
            if parent in self._data["folder_cases"]:
                return self._data["folder_cases"][parent]
        return ""

    def set_case_number(self, folder_path: str, case_number: str):
        normalized = os.path.normpath(folder_path)
        if case_number:
            self._data["folder_cases"][normalized] = case_number
        elif normalized in self._data["folder_cases"]:
            del self._data["folder_cases"][normalized]
        self._save()

    def get_all_case_mappings(self) -> dict[str, str]:
        return dict(self._data["folder_cases"])
