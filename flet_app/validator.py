"""File quality validation logic shared between apps."""

import hashlib
import os
import re


def format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

# Windows-invalid characters in filenames
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Max path length on Windows
MAX_PATH_LENGTH = 260

# Legacy Office formats that should be converted
LEGACY_FORMATS = {
    ".doc": ".docx",
    ".xls": ".xlsx",
    ".ppt": ".pptx",
    ".dot": ".dotx",
    ".xlt": ".xltx",
    ".pot": ".potx",
}


def validate_file(info: dict) -> list[str]:
    """Return a list of warning strings for the given file info dict."""
    warnings = []
    name = info["name"]
    path = info["path"]
    ext = info["ext"]
    size = info["size"]

    # Empty file
    if size == 0:
        warnings.append("Tom fil (0 bytes)")

    # Legacy format
    if ext in LEGACY_FORMATS:
        warnings.append(f"Forældet format – bør konverteres til {LEGACY_FORMATS[ext]}")

    # Invalid characters in filename (excluding path separators)
    basename_no_ext = os.path.splitext(name)[0]
    if INVALID_CHARS.search(basename_no_ext):
        warnings.append("Ugyldige tegn i filnavn")

    # Filename starts or ends with space/dot
    if name != name.strip() or basename_no_ext.endswith("."):
        warnings.append("Filnavn starter/slutter med mellemrum eller punktum")

    # Path too long for Windows
    if len(path) > MAX_PATH_LENGTH:
        warnings.append(f"Sti for lang ({len(path)} tegn, max {MAX_PATH_LENGTH})")

    return warnings


def compute_file_hash(path: str, chunk_size: int = 65536) -> str:
    """Compute MD5 hash of a file for duplicate detection."""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
    except (OSError, PermissionError):
        return ""
    return h.hexdigest()


def find_duplicates(results: list[dict]) -> dict[str, list[dict]]:
    """Group files by hash. Returns only groups with 2+ files (duplicates).

    First groups by size (fast), then hashes only size-matched files.
    """
    # Group by size first (cheap)
    by_size = {}
    for info in results:
        size = info["size"]
        if size == 0:
            continue
        by_size.setdefault(size, []).append(info)

    # Only hash files that share a size
    by_hash = {}
    for size, group in by_size.items():
        if len(group) < 2:
            continue
        for info in group:
            file_hash = compute_file_hash(info["path"])
            if file_hash:
                by_hash.setdefault(file_hash, []).append(info)

    return {h: files for h, files in by_hash.items() if len(files) >= 2}
