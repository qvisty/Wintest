"""Export and report generation for the file index."""

import csv
import os
from datetime import datetime
from database import FileIndex
from validator import format_size


def export_csv(db: FileIndex, output_path: str, filters: dict = None,
               include_metadata: bool = False):
    """Export file index to CSV with optional filters.

    Args:
        db: FileIndex instance
        output_path: Path to write CSV file
        filters: Dict of search kwargs (query, ext, status, tag, etc.)
        include_metadata: Whether to include metadata columns
    """
    filters = filters or {}
    files = db.search(**filters, limit=999999)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")

        headers = ["Filnavn", "Type", "Størrelse (bytes)", "Størrelse",
                    "Ændret", "Status", "Advarsler", "Tags", "Sagsnr.", "Fuld sti"]
        if include_metadata:
            # Collect all metadata keys
            all_meta_keys = set()
            for file in files:
                all_meta_keys.update(file.get("metadata", {}).keys())
            meta_keys = sorted(all_meta_keys)
            headers.extend(meta_keys)

        writer.writerow(headers)

        for file in files:
            warnings = "; ".join(file.get("warnings", []))
            tags = ", ".join(file.get("tags", []))
            case = db.get_case_number(os.path.dirname(file["path"]))

            row = [
                file["name"],
                file["ext"],
                file["size"],
                format_size(file["size"]),
                file["modified"],
                file.get("status", ""),
                warnings,
                tags,
                case,
                file["path"],
            ]

            if include_metadata:
                meta = file.get("metadata", {})
                for key in meta_keys:
                    row.append(meta.get(key, ""))

            writer.writerow(row)

    return len(files)


def generate_html_report(db: FileIndex) -> str:
    """Generate a comprehensive HTML quality report."""
    stats = db.get_stats()
    duplicates = db.find_duplicates()

    lines = [
        "<html><head><meta charset='utf-8'>",
        "<style>body{font-family:Segoe UI,sans-serif;margin:20px;} "
        "table{border-collapse:collapse;width:100%;margin:10px 0;} "
        "th,td{border:1px solid #ddd;padding:6px 10px;text-align:left;} "
        "th{background:#f0f0f0;} .warn{color:#c60;} .ok{color:#090;} "
        "h1{color:#333;} h2{color:#555;border-bottom:1px solid #ddd;padding-bottom:5px;}"
        "</style></head><body>",
        f"<h1>ESDH Kvalitetsrapport</h1>",
        f"<p>Genereret: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>",

        # Summary
        "<h2>Overblik</h2>",
        "<table>",
        f"<tr><td>Antal filer</td><td><b>{stats['total_files']}</b></td></tr>",
        f"<tr><td>Samlet størrelse</td><td><b>{format_size(stats['total_size'])}</b></td></tr>",
        f"<tr><td>Metadata udtrukket</td><td><b>{stats['metadata_extracted']}</b> / {stats['total_files']}</td></tr>",
        f"<tr><td>Med advarsler</td><td class='warn'><b>{stats['with_warnings']}</b></td></tr>",
        f"<tr><td>Med tags</td><td><b>{stats['with_tags']}</b></td></tr>",
        "</table>",
    ]

    # Status breakdown
    if stats["by_status"]:
        lines.append("<h2>Status-fordeling</h2><table><tr><th>Status</th><th>Antal</th></tr>")
        for status, cnt in stats["by_status"].items():
            lines.append(f"<tr><td>{status}</td><td>{cnt}</td></tr>")
        lines.append("</table>")

    # Extensions
    if stats["by_ext"]:
        lines.append("<h2>Filtyper</h2><table><tr><th>Type</th><th>Antal</th><th>Størrelse</th></tr>")
        for ext_info in stats["by_ext"]:
            lines.append(
                f"<tr><td>{ext_info['ext'] or '(ingen)'}</td>"
                f"<td>{ext_info['count']}</td>"
                f"<td>{format_size(ext_info['size'])}</td></tr>"
            )
        lines.append("</table>")

    # Tags
    if stats["by_tag"]:
        lines.append("<h2>Tags</h2><table><tr><th>Tag</th><th>Antal filer</th></tr>")
        for tag, cnt in stats["by_tag"].items():
            lines.append(f"<tr><td>{tag}</td><td>{cnt}</td></tr>")
        lines.append("</table>")

    # Warnings
    warn_files = db.search(has_warnings=True, limit=999999)
    if warn_files:
        warn_types = {}
        for f in warn_files:
            for w in f["warnings"]:
                warn_types.setdefault(w, []).append(f)

        lines.append(f"<h2>Advarsler ({len(warn_files)} filer)</h2>")
        for wtype, files in sorted(warn_types.items(), key=lambda x: -len(x[1])):
            lines.append(f"<h3>{wtype} ({len(files)} filer)</h3><ul>")
            for f in files[:50]:
                lines.append(f"<li>{f['name']} <span style='color:gray'>– {f['path']}</span></li>")
            if len(files) > 50:
                lines.append(f"<li><i>...og {len(files) - 50} flere</i></li>")
            lines.append("</ul>")

    # Duplicates
    if duplicates:
        total_dup = sum(len(g) for g in duplicates)
        wasted = sum(sum(f["size"] for f in g[1:]) for g in duplicates)
        lines.append(f"<h2>Dubletter ({total_dup} filer, spildplads: {format_size(wasted)})</h2>")
        for i, group in enumerate(duplicates[:50], 1):
            lines.append(
                f"<h3>Gruppe {i} ({len(group)} filer, {format_size(group[0]['size'])} hver)</h3><ul>"
            )
            for f in group:
                lines.append(f"<li>{f['path']}</li>")
            lines.append("</ul>")

    # Case mappings
    case_mappings = db.get_all_case_mappings()
    if case_mappings:
        lines.append("<h2>Sagsnr.-oversigt</h2><table><tr><th>Mappe</th><th>Sagsnr.</th></tr>")
        for folder, case in sorted(case_mappings.items()):
            lines.append(f"<tr><td>{folder}</td><td><b>{case}</b></td></tr>")
        lines.append("</table>")

    lines.append("</body></html>")
    return "\n".join(lines)


def export_html_report(db: FileIndex, output_path: str):
    """Write HTML report to file."""
    html = generate_html_report(db)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
