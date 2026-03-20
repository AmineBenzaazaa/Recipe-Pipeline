import logging
import re
from types import SimpleNamespace

import pytest
import requests

import sheet_image_worker as worker
from sheet_image_worker import (
    _discover_target_worksheets,
    _match_sheet_tab_title,
    _resolve_column_indices,
    _resolve_worksheet,
    _wait_imagineapi_completion,
)


class _FakeWorksheet:
    def __init__(self, title: str) -> None:
        self.title = title


class _FakeSheet:
    def __init__(self, titles):
        self._worksheets = [_FakeWorksheet(title) for title in titles]
        self.sheet1 = self._worksheets[0]

    def worksheets(self):
        return self._worksheets


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += float(seconds)


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self) -> dict:
        return self._payload


class _Cell:
    def __init__(self, value: str) -> None:
        self.value = value


class _GridWorksheet:
    def __init__(self, title: str, rows: list[list[str]]) -> None:
        self.title = title
        self._rows = [list(row) for row in rows]
        self.update_history: list[tuple[str, str]] = []
        self.read_overrides: dict[str, object] = {}

    @staticmethod
    def _a1_to_pos(a1: str) -> tuple[int, int]:
        match = re.match(r"^([A-Z]+)(\d+)$", a1)
        if not match:
            raise ValueError(f"Invalid A1 reference: {a1}")
        letters, row_text = match.groups()
        col_value = 0
        for char in letters:
            col_value = col_value * 26 + (ord(char) - 64)
        return int(row_text) - 1, col_value - 1

    def _ensure_size(self, row_index: int, col_index: int) -> None:
        while len(self._rows) <= row_index:
            self._rows.append([])
        row = self._rows[row_index]
        if len(row) <= col_index:
            row.extend([""] * (col_index + 1 - len(row)))

    def get_all_values(self):
        return [list(row) for row in self._rows]

    def batch_update(self, payload, value_input_option="USER_ENTERED"):
        for item in payload:
            a1 = item["range"]
            value = item["values"][0][0]
            row_index, col_index = self._a1_to_pos(a1)
            self._ensure_size(row_index, col_index)
            self._rows[row_index][col_index] = value
            self.update_history.append((a1, value))

    def acell(self, a1: str):
        row_index, col_index = self._a1_to_pos(a1)
        self._ensure_size(row_index, col_index)
        value = self._rows[row_index][col_index]
        override = self.read_overrides.get(a1)
        if callable(override):
            value = override(value)
        elif override is not None:
            value = override
        return _Cell(value)


def _headers(include_optional: bool = False):
    headers = [
        "status",
        "featured_image_prompt",
        "featured_image_generated_url",
        "instructions_process_image_prompt",
        "instructions_process_image_generated_url",
        "serving_image_prompt",
        "serving_image_generated_url",
    ]
    if include_optional:
        headers.extend(
            [
                "ingredients_image_prompt",
                "ingredients_image_generated_url",
                "pin_image_prompt",
                "pin_image_generated_url",
            ]
        )
    return headers


def _settings():
    return SimpleNamespace(
        imagine_api_url="https://example.com",
        imagine_api_token="token",
        imagine_api_poll_seconds=2,
        request_timeout=5.0,
    )


def _run_process_rows(worksheet, logger):
    return worker._process_generate_rows(
        worksheet=worksheet,
        headers=_headers(),
        status_col=0,
        featured_prompt_col=1,
        featured_url_col=2,
        instructions_prompt_col=3,
        instructions_url_col=4,
        serving_prompt_col=5,
        serving_url_col=6,
        generate_value="Generate",
        generating_value="Generating",
        ready_value="Ready",
        settings=_settings(),
        upscale_index=2,
        timeout_seconds=30,
        logger=logger,
        max_rows=0,
        enable_row_claim=True,
        claim_worker_id="worker-a",
        claim_settle_seconds=0.0,
        generating_stale_seconds=900,
    )


def test_match_sheet_tab_title_exact():
    titles = ["Easydogmeals.com", "Other"]
    assert _match_sheet_tab_title("Easydogmeals.com", titles) == "Easydogmeals.com"


def test_match_sheet_tab_title_case_insensitive():
    titles = ["Easydogmeals.com", "Other"]
    assert _match_sheet_tab_title("easydogmeals.com", titles) == "Easydogmeals.com"


def test_match_sheet_tab_title_missing():
    titles = ["Easydogmeals.com", "Other"]
    assert _match_sheet_tab_title("MissingTab", titles) is None


def test_resolve_worksheet_uses_sheet1_when_tab_is_blank():
    sheet = _FakeSheet(["First", "Second"])
    logger = logging.getLogger("sheet_image_worker_test")
    resolved = _resolve_worksheet(sheet, "   ", logger)
    assert resolved.title == "First"


def test_resolve_worksheet_raises_helpful_error_for_missing_tab():
    sheet = _FakeSheet(["Easydogmeals.com", "Other"])
    logger = logging.getLogger("sheet_image_worker_test")
    with pytest.raises(ValueError) as exc_info:
        _resolve_worksheet(sheet, "MissingTab", logger)
    message = str(exc_info.value)
    assert "MissingTab" in message
    assert "Easydogmeals.com, Other" in message


def test_resolve_column_indices_uses_fallback_status_header():
    logger = logging.getLogger("sheet_image_worker_test")
    headers = [
        "Ready",
        "featured_image_prompt",
        "featured_image_generated_url",
        "instructions_process_image_prompt",
        "instructions_process_image_generated_url",
        "serving_image_prompt",
        "serving_image_generated_url",
    ]

    col_indices, missing, status_used = _resolve_column_indices(
        headers=headers,
        status_column_name="status",
        logger=logger,
    )

    assert missing == []
    assert status_used == "Ready"
    assert col_indices["status"] == 0


def test_resolve_column_indices_includes_optional_prompt_columns_when_present():
    logger = logging.getLogger("sheet_image_worker_test")

    col_indices, missing, _status_used = _resolve_column_indices(
        headers=_headers(include_optional=True),
        status_column_name="status",
        logger=logger,
    )

    assert missing == []
    assert "ingredients_image_prompt" in col_indices
    assert "ingredients_image_generated_url" in col_indices
    assert "pin_image_prompt" in col_indices
    assert "pin_image_generated_url" in col_indices


def test_discover_target_worksheets_returns_all_tabs_when_enabled():
    logger = logging.getLogger("sheet_image_worker_test")
    sheet = _FakeSheet(["First", "Second", "Third"])

    worksheets = _discover_target_worksheets(
        sheet=sheet,
        all_tabs=True,
        requested_tab="",
        logger=logger,
    )

    assert [worksheet.title for worksheet in worksheets] == ["First", "Second", "Third"]


def test_wait_imagineapi_completion_retries_poll_request_errors(monkeypatch, caplog):
    logger = logging.getLogger("sheet_image_worker_test")
    caplog.set_level(logging.INFO, logger="sheet_image_worker_test")
    clock = _FakeClock()
    monkeypatch.setattr(worker.time, "time", clock.time)
    monkeypatch.setattr(worker.time, "sleep", clock.sleep)

    calls = {"count": 0}

    def _fake_get(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.RequestException("temporary failure")
        return _FakeResponse(
            {"data": {"status": "completed", "progress": "100", "url": "https://example.com/img.png"}}
        )

    monkeypatch.setattr(worker.requests, "get", _fake_get)

    payload = _wait_imagineapi_completion(
        base_url="https://example.com",
        token="token",
        image_id="img123",
        poll_seconds=5,
        timeout_seconds=60,
        request_timeout=5.0,
        logger=logger,
    )

    assert payload["status"] == "completed"
    assert "Status poll failed for image img123: temporary failure" in caplog.text


def test_wait_imagineapi_completion_timeout_reports_last_state(monkeypatch, caplog):
    logger = logging.getLogger("sheet_image_worker_test")
    caplog.set_level(logging.INFO, logger="sheet_image_worker_test")
    clock = _FakeClock()
    monkeypatch.setattr(worker.time, "time", clock.time)
    monkeypatch.setattr(worker.time, "sleep", clock.sleep)
    monkeypatch.setattr(
        worker.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse({"data": {"status": "pending", "progress": None}}),
    )

    with pytest.raises(TimeoutError) as exc_info:
        _wait_imagineapi_completion(
            base_url="https://example.com",
            token="token",
            image_id="img123",
            poll_seconds=20,
            timeout_seconds=65,
            request_timeout=5.0,
            logger=logger,
        )

    message = str(exc_info.value)
    assert "last status=pending" in message
    assert "progress=-" in message
    assert "still waiting: status=pending" in caplog.text


def test_process_generate_rows_claims_then_completes(monkeypatch):
    logger = logging.getLogger("sheet_image_worker_test")
    worksheet = _GridWorksheet(
        "Tab1",
        [
            _headers(),
            ["Generate", "featured prompt", "", "instructions prompt", "", "serving prompt", ""],
        ],
    )
    monkeypatch.setattr(worker.time, "time", lambda: 1700000000.0)
    monkeypatch.setattr(worker.time, "sleep", lambda *_: None)

    generated = []

    def _fake_generate(**kwargs):
        generated.append(kwargs["image_type"])
        return f"https://cdn.example/{kwargs['image_type']}.png"

    monkeypatch.setattr(worker, "_generate_u2_cloudinary_url", _fake_generate)

    matched, completed = _run_process_rows(worksheet, logger)

    assert matched == 1
    assert completed == 1
    assert generated == ["featured", "instructions-process", "serving"]
    final_rows = worksheet.get_all_values()
    assert final_rows[1][0] == "Ready"
    claim_updates = [
        value
        for a1, value in worksheet.update_history
        if a1 == "A2" and str(value).startswith("Generating|worker-a|")
    ]
    assert claim_updates


def test_process_generate_rows_skips_when_claim_not_acquired(monkeypatch):
    logger = logging.getLogger("sheet_image_worker_test")
    worksheet = _GridWorksheet(
        "Tab1",
        [
            _headers(),
            ["Generate", "featured prompt", "", "instructions prompt", "", "serving prompt", ""],
        ],
    )
    worksheet.read_overrides["A2"] = "Generating|other-worker|1700000001000"
    monkeypatch.setattr(worker.time, "time", lambda: 1700000000.0)
    monkeypatch.setattr(worker.time, "sleep", lambda *_: None)

    called = {"value": 0}

    def _fake_generate(**kwargs):
        called["value"] += 1
        return "https://cdn.example/unused.png"

    monkeypatch.setattr(worker, "_generate_u2_cloudinary_url", _fake_generate)

    matched, completed = _run_process_rows(worksheet, logger)

    assert matched == 1
    assert completed == 0
    assert called["value"] == 0


def test_process_generate_rows_resets_status_after_failure(monkeypatch):
    logger = logging.getLogger("sheet_image_worker_test")
    worksheet = _GridWorksheet(
        "Tab1",
        [
            _headers(),
            ["Generate", "featured prompt", "", "instructions prompt", "", "serving prompt", ""],
        ],
    )
    monkeypatch.setattr(worker.time, "time", lambda: 1700000000.0)
    monkeypatch.setattr(worker.time, "sleep", lambda *_: None)

    def _raise_generate(**kwargs):
        raise RuntimeError("image generation failed")

    monkeypatch.setattr(worker, "_generate_u2_cloudinary_url", _raise_generate)

    matched, completed = _run_process_rows(worksheet, logger)

    assert matched == 1
    assert completed == 0
    final_rows = worksheet.get_all_values()
    assert final_rows[1][0] == "Generate"


def test_process_generate_rows_reclaims_stale_generating_row(monkeypatch):
    logger = logging.getLogger("sheet_image_worker_test")
    worksheet = _GridWorksheet(
        "Tab1",
        [
            _headers(),
            [
                "Generating|other-worker|1699998000000",
                "featured prompt",
                "",
                "instructions prompt",
                "",
                "serving prompt",
                "",
            ],
        ],
    )
    monkeypatch.setattr(worker.time, "time", lambda: 1700000000.0)
    monkeypatch.setattr(worker.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        worker,
        "_generate_u2_cloudinary_url",
        lambda **kwargs: f"https://cdn.example/{kwargs['image_type']}.png",
    )

    matched, completed = _run_process_rows(worksheet, logger)

    assert matched == 1
    assert completed == 1
    assert worksheet.get_all_values()[1][0] == "Ready"


def test_process_generate_rows_skips_non_stale_generating_row(monkeypatch):
    logger = logging.getLogger("sheet_image_worker_test")
    worksheet = _GridWorksheet(
        "Tab1",
        [
            _headers(),
            [
                "Generating|other-worker|1699999950000",
                "featured prompt",
                "",
                "instructions prompt",
                "",
                "serving prompt",
                "",
            ],
        ],
    )
    monkeypatch.setattr(worker.time, "time", lambda: 1700000000.0)
    monkeypatch.setattr(worker.time, "sleep", lambda *_: None)

    called = {"value": 0}

    def _fake_generate(**kwargs):
        called["value"] += 1
        return "https://cdn.example/unused.png"

    monkeypatch.setattr(worker, "_generate_u2_cloudinary_url", _fake_generate)

    matched, completed = _run_process_rows(worksheet, logger)

    assert matched == 0
    assert completed == 0
    assert called["value"] == 0


def test_process_generate_rows_updates_optional_ingredients_and_pin_images(monkeypatch):
    logger = logging.getLogger("sheet_image_worker_test")
    headers = _headers(include_optional=True)
    worksheet = _GridWorksheet(
        "Tab1",
        [
            headers,
            [
                "Generate",
                "featured prompt",
                "",
                "instructions prompt",
                "",
                "serving prompt",
                "",
                "ingredients prompt",
                "",
                "pin prompt",
                "",
            ],
        ],
    )
    monkeypatch.setattr(worker.time, "time", lambda: 1700000000.0)
    monkeypatch.setattr(worker.time, "sleep", lambda *_: None)

    generated = []

    def _fake_generate(**kwargs):
        generated.append(kwargs["image_type"])
        return f"https://cdn.example/{kwargs['image_type']}.png"

    monkeypatch.setattr(worker, "_generate_u2_cloudinary_url", _fake_generate)

    matched, completed = worker._process_generate_rows(
        worksheet=worksheet,
        headers=headers,
        status_col=0,
        featured_prompt_col=1,
        featured_url_col=2,
        instructions_prompt_col=3,
        instructions_url_col=4,
        serving_prompt_col=5,
        serving_url_col=6,
        generate_value="Generate",
        generating_value="Generating",
        ready_value="Ready",
        settings=_settings(),
        upscale_index=2,
        timeout_seconds=30,
        logger=logger,
        max_rows=0,
        enable_row_claim=True,
        claim_worker_id="worker-a",
        claim_settle_seconds=0.0,
        generating_stale_seconds=900,
        optional_image_columns={"ingredients": (7, 8), "pin": (9, 10)},
    )

    assert matched == 1
    assert completed == 1
    assert generated == ["featured", "instructions-process", "serving", "ingredients", "pin"]
