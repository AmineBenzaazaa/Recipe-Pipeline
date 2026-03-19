import logging
from pathlib import Path
from typing import List, Optional


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
        if not credentials_path:
            raise ValueError("Google service account JSON path is required")

        self._logger = logger
        self._ready_value = ready_value or ""

        import gspread

        credentials_file = str(Path(credentials_path).expanduser())
        client = gspread.service_account(filename=credentials_file)
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


def list_sheet_worksheets(sheet_url: str, credentials_path: str) -> List[str]:
    if not sheet_url:
        raise ValueError("Google Sheet URL is required")
    if not credentials_path:
        raise ValueError("Google service account JSON path is required")

    import gspread

    credentials_file = str(Path(credentials_path).expanduser())
    client = gspread.service_account(filename=credentials_file)
    sheet = client.open_by_url(sheet_url)
    return [ws.title for ws in sheet.worksheets()]
