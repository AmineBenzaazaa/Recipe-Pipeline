import json
import logging
import os
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
            return headers
        if not expected_headers:
            raise ValueError("Sheet is missing headers and no expected headers were provided")
        self._worksheet.update("1:1", [expected_headers])
        return list(expected_headers)

    def append_row(self, row: dict) -> None:
        if not self._headers:
            raise ValueError("Sheet headers are not configured")
        values: List[str] = []
        for header in self._headers:
            if header in row and row[header] is not None:
                values.append(str(row[header]))
                continue
            if header.strip().lower() == "ready":
                values.append(self._ready_value)
            else:
                values.append("")
        self._worksheet.append_row(values, value_input_option="USER_ENTERED")


def list_sheet_worksheets(sheet_url: str, credentials_path: str = "") -> List[str]:
    if not sheet_url:
        raise ValueError("Google Sheet URL is required")

    client = get_gspread_client(credentials_path)
    sheet = client.open_by_url(sheet_url)
    return [ws.title for ws in sheet.worksheets()]
