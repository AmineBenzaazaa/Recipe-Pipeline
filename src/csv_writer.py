import csv
import os
from typing import Dict, List


def load_template_headers(template_path: str) -> List[str]:
    with open(template_path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        headers = next(reader, [])
    if not headers:
        raise ValueError("Template CSV has no headers")
    return headers


def ensure_output_headers(out_path: str, headers: List[str]) -> None:
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        with open(out_path, newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            existing = next(reader, [])
        if existing != headers:
            raise ValueError("Output CSV headers do not match template")
        return
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)


def append_row(out_path: str, headers: List[str], row: Dict[str, str]) -> None:
    ensure_output_headers(out_path, headers)
    with open(out_path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writerow({key: row.get(key, "") for key in headers})
