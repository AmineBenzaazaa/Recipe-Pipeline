import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


GOOGLE_SHEET_CREDENTIALS_INFO_ENV = "GOOGLE_SHEET_CREDENTIALS_INFO"
GOOGLE_SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _load_google_credentials_from_streamlit_secrets() -> Optional[Dict[str, Any]]:
    try:
        import streamlit as st
    except ImportError:
        return None

    try:
        if "gcp_service_account" not in st.secrets:
            return None
        return dict(st.secrets["gcp_service_account"])
    except Exception:
        return None


def load_google_credentials_from_streamlit_secrets() -> Optional[Dict[str, Any]]:
    return _load_google_credentials_from_streamlit_secrets()


def _load_google_credentials_from_env() -> Optional[Dict[str, Any]]:
    raw = (os.getenv(GOOGLE_SHEET_CREDENTIALS_INFO_ENV, "") or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{GOOGLE_SHEET_CREDENTIALS_INFO_ENV} must contain valid JSON service account credentials."
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"{GOOGLE_SHEET_CREDENTIALS_INFO_ENV} must contain a JSON object."
        )
    return parsed


def _load_google_credentials_from_file(credentials_path: str = "") -> Optional[Dict[str, Any]]:
    candidate = (credentials_path or os.getenv("GOOGLE_SHEET_CREDENTIALS", "")).strip()
    if not candidate:
        return None

    path = Path(candidate).expanduser()
    if not path.exists():
        raise RuntimeError(f"Google credentials file not found: {path}")

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Failed to read Google credentials file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Google credentials file is not valid JSON: {path}") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"Google credentials file must contain a JSON object: {path}")
    return parsed


def google_credentials_configured(credentials_path: str = "") -> bool:
    try:
        info = _load_google_credentials_from_streamlit_secrets()
        if info:
            return True

        info = _load_google_credentials_from_env()
        if info:
            return True

        info = _load_google_credentials_from_file(credentials_path)
        if info:
            return True
    except RuntimeError:
        return False

    return False


def get_google_credentials(credentials_path: str = ""):
    from google.oauth2.service_account import Credentials

    info = _load_google_credentials_from_streamlit_secrets()
    if not info:
        info = _load_google_credentials_from_env()
    if not info:
        info = _load_google_credentials_from_file(credentials_path)
    if not info:
        raise RuntimeError(
            "Google credentials are not configured. "
            "Set st.secrets['gcp_service_account'] or provide a local GOOGLE_SHEET_CREDENTIALS JSON path."
        )

    return Credentials.from_service_account_info(info, scopes=GOOGLE_SHEETS_SCOPES)


def get_gspread_client(credentials_path: str = ""):
    import gspread

    return gspread.authorize(get_google_credentials(credentials_path))


class GoogleSheetWriter:
    def __init__(
        self,
        sheet_url: str,
        worksheet_title: Optional[str],
        credentials_path: str,
        logger: logging.Logger,
        expected_headers: Optional[List[str]] = None,
        ready_value: str = "",
    ) -> None:
        if not sheet_url:
            raise ValueError("Google Sheet URL is required")

        self._logger = logger
        self._ready_value = ready_value or ""

        import gspread

        client = get_gspread_client(credentials_path)
        sheet = client.open_by_url(sheet_url)
        if worksheet_title:
            requested = worksheet_title.strip()
            worksheet = None
            try:
                worksheet = sheet.worksheet(requested)
            except gspread.WorksheetNotFound:
                requested_folded = requested.casefold()
                for candidate in sheet.worksheets():
                    candidate_title = (candidate.title or "").strip()
                    if candidate_title.casefold() == requested_folded:
                        worksheet = candidate
                        self._logger.warning(
                            "Worksheet '%s' not found with exact case; using '%s'",
                            requested,
                            candidate_title,
                        )
                        break
                if worksheet is None:
                    available = ", ".join(
                        (ws.title or "").strip() for ws in sheet.worksheets()
                    ) or "<none>"
                    raise ValueError(
                        f"Worksheet '{requested}' not found. Available tabs: {available}"
                    )
        else:
            worksheet = sheet.sheet1
        self._worksheet = worksheet
        self._headers = self._load_headers(expected_headers)

    @property
    def headers(self) -> List[str]:
        return list(self._headers)

    def _load_headers(self, expected_headers: Optional[List[str]]) -> List[str]:
        headers = self._worksheet.row_values(1)
        if headers:
            if not expected_headers:
                return headers

            merged_headers, added_headers = _merge_sheet_headers(headers, expected_headers)
            if added_headers:
                self._worksheet.update("1:1", [merged_headers])
                self._logger.warning(
                    "Added missing Google Sheet headers: %s",
                    ", ".join(added_headers),
                )
            return merged_headers
        if not expected_headers:
            raise ValueError("Sheet is missing headers and no expected headers were provided")
        self._worksheet.update("1:1", [expected_headers])
        return list(expected_headers)

    def append_row(self, row: dict) -> None:
        if not self._headers:
            raise ValueError("Sheet headers are not configured")
        values = _build_row_values(self._headers, row, self._ready_value)
        self._worksheet.append_row(
            values,
            value_input_option="USER_ENTERED",
            table_range="A1",
        )

    def upsert_row(self, row: dict) -> str:
        if not self._headers:
            raise ValueError("Sheet headers are not configured")

        normalized_row = _normalize_row_keys(row)
        matched_row_index = self._find_matching_row_index(normalized_row)
        if matched_row_index is None:
            self.append_row(row)
            return "appended"

        payload = _build_row_update_payload(
            headers=self._headers,
            normalized_row=normalized_row,
            row_index=matched_row_index,
            ready_value=self._ready_value,
        )
        if not payload:
            return "skipped"

        self._worksheet.batch_update(payload, value_input_option="USER_ENTERED")
        return "updated"

    def _find_matching_row_index(self, normalized_row: Dict[str, Any]) -> Optional[int]:
        source_match = _extract_match_values_from_row(normalized_row)
        if not any(source_match.values()):
            return None

        values = self._worksheet.get_all_values()
        if len(values) <= 1:
            return None

        header_indices = _header_index_map(self._headers)
        keyword_matches: List[int] = []
        for row_index, row_values in enumerate(values[1:], start=2):
            candidate_match = _extract_match_values_from_sheet_row(row_values, header_indices)
            if source_match["recipe_url"] and candidate_match["recipe_url"]:
                if source_match["recipe_url"] == candidate_match["recipe_url"]:
                    return row_index
                continue
            if source_match["pinterest_url"] and candidate_match["pinterest_url"]:
                if source_match["pinterest_url"] == candidate_match["pinterest_url"]:
                    return row_index
                continue
            if source_match["keyword"] and candidate_match["keyword"]:
                if source_match["keyword"] == candidate_match["keyword"]:
                    keyword_matches.append(row_index)

        if len(keyword_matches) == 1:
            return keyword_matches[0]

        if len(keyword_matches) > 1:
            self._logger.warning(
                "Multiple matching sheet rows found for keyword '%s'; appending instead of updating in place.",
                source_match["keyword"],
            )
        return None


def _normalize_header_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def _merge_sheet_headers(
    existing_headers: List[str],
    expected_headers: List[str],
) -> tuple[List[str], List[str]]:
    merged_headers = list(existing_headers)
    existing_normalized = {
        _normalize_header_key(header)
        for header in existing_headers
        if _normalize_header_key(header)
    }
    added_headers: List[str] = []

    for header in expected_headers:
        normalized = _normalize_header_key(header)
        if not normalized or normalized in existing_normalized:
            continue
        merged_headers.append(header)
        existing_normalized.add(normalized)
        added_headers.append(header)

    return merged_headers, added_headers


def _normalize_row_keys(row: dict) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in (row or {}).items():
        normalized_key = _normalize_header_key(str(key))
        if normalized_key and normalized_key not in normalized:
            normalized[normalized_key] = value
    return normalized


def _build_row_values(headers: List[str], row: dict, ready_value: str) -> List[str]:
    normalized_row = _normalize_row_keys(row)
    values: List[str] = []
    for header in headers:
        if header in row and row[header] is not None:
            values.append(str(row[header]))
            continue

        normalized_header = _normalize_header_key(header)
        if normalized_header in normalized_row and normalized_row[normalized_header] is not None:
            values.append(str(normalized_row[normalized_header]))
            continue

        if header.strip().lower() == "ready":
            values.append(ready_value)
        else:
            values.append("")
    return values


def _normalize_match_value(value: Any) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"\s+", " ", cleaned)
    if "://" in cleaned:
        cleaned = cleaned.rstrip("/")
    return cleaned.casefold()


def _first_non_empty(mapping: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _normalize_match_value(mapping.get(key, ""))
        if value:
            return value
    return ""


def _header_index_map(headers: List[str]) -> Dict[str, int]:
    header_indices: Dict[str, int] = {}
    for index, header in enumerate(headers):
        normalized = _normalize_header_key(header)
        if normalized and normalized not in header_indices:
            header_indices[normalized] = index
    return header_indices


def _read_row_value(row_values: List[str], index: Optional[int]) -> str:
    if index is None or index < 0 or index >= len(row_values):
        return ""
    return row_values[index]


def _extract_match_values_from_row(normalized_row: Dict[str, Any]) -> Dict[str, str]:
    return {
        "keyword": _first_non_empty(normalized_row, "focus_keyword", "recipe_name", "topic"),
        "recipe_url": _first_non_empty(normalized_row, "recipe_url", "url"),
        "pinterest_url": _first_non_empty(normalized_row, "pinterest_url"),
    }


def _extract_match_values_from_sheet_row(
    row_values: List[str],
    header_indices: Dict[str, int],
) -> Dict[str, str]:
    row_mapping = {
        key: _read_row_value(row_values, index)
        for key, index in header_indices.items()
    }
    return _extract_match_values_from_row(row_mapping)


def _column_to_a1(col_index_zero_based: int) -> str:
    value = col_index_zero_based + 1
    chars: List[str] = []
    while value > 0:
        value, rem = divmod(value - 1, 26)
        chars.append(chr(65 + rem))
    return "".join(reversed(chars))


def _build_row_update_payload(
    *,
    headers: List[str],
    normalized_row: Dict[str, Any],
    row_index: int,
    ready_value: str,
) -> List[dict]:
    payload: List[dict] = []
    for col_index, header in enumerate(headers):
        normalized_header = _normalize_header_key(header)
        if normalized_header in normalized_row:
            value = normalized_row[normalized_header]
        elif normalized_header == "ready":
            value = ready_value
        else:
            continue
        payload.append(
            {
                "range": f"{_column_to_a1(col_index)}{row_index}",
                "values": [[str(value or "")]],
            }
        )
    return payload


def list_sheet_worksheets(sheet_url: str, credentials_path: str = "") -> List[str]:
    if not sheet_url:
        raise ValueError("Google Sheet URL is required")

    client = get_gspread_client(credentials_path)
    sheet = client.open_by_url(sheet_url)
    return [ws.title for ws in sheet.worksheets()]
