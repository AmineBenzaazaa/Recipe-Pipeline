from src.sheets_client import GoogleSheetWriter, _merge_sheet_headers


class _FakeWorksheet:
    def __init__(self, headers, rows=None):
        self._headers = list(headers)
        self._rows = [list(headers)]
        if rows:
            self._rows.extend([list(row) for row in rows])
        self.updated_rows = []
        self.appended_rows = []
        self.batch_updates = []

    def row_values(self, row_number):
        assert row_number == 1
        return list(self._headers)

    def get_all_values(self):
        return [list(row) for row in self._rows]

    def update(self, _range, values):
        self.updated_rows.append((_range, values))
        if values and values[0]:
            self._headers = list(values[0])
            if self._rows:
                self._rows[0] = list(values[0])

    def append_row(self, values, value_input_option="USER_ENTERED", table_range=None):
        self.appended_rows.append((list(values), value_input_option, table_range))
        self._rows.append(list(values))

    def batch_update(self, payload, value_input_option="USER_ENTERED"):
        self.batch_updates.append((payload, value_input_option))
        for item in payload:
            a1 = item["range"]
            col_letters = "".join(ch for ch in a1 if ch.isalpha())
            row_number = int("".join(ch for ch in a1 if ch.isdigit()))
            col_index = 0
            for char in col_letters:
                col_index = col_index * 26 + (ord(char) - 64)
            col_index -= 1
            while len(self._rows) < row_number:
                self._rows.append([])
            while len(self._rows[row_number - 1]) <= col_index:
                self._rows[row_number - 1].append("")
            self._rows[row_number - 1][col_index] = item["values"][0][0]


class _FakeLogger:
    def __init__(self):
        self.messages = []

    def warning(self, message, *args):
        self.messages.append(message % args if args else message)


def test_merge_sheet_headers_appends_missing_expected_headers():
    merged, added = _merge_sheet_headers(
        [
            "focus_keyword",
            "topic",
            "featured_image_url",
        ],
        [
            "focus_keyword",
            "topic",
            "featured_image_prompt",
            "featured_image_generated_url",
        ],
    )

    assert merged == [
        "focus_keyword",
        "topic",
        "featured_image_url",
        "featured_image_prompt",
        "featured_image_generated_url",
    ]
    assert added == [
        "featured_image_prompt",
        "featured_image_generated_url",
    ]


def test_google_sheet_writer_load_headers_upgrades_legacy_sheet_headers():
    worksheet = _FakeWorksheet(
        [
            "focus_keyword",
            "topic",
            "featured_image_url",
        ]
    )
    writer = GoogleSheetWriter.__new__(GoogleSheetWriter)
    writer._worksheet = worksheet
    writer._logger = _FakeLogger()
    writer._ready_value = "ready"

    loaded = writer._load_headers(
        [
            "focus_keyword",
            "topic",
            "featured_image_prompt",
            "featured_image_generated_url",
        ]
    )

    assert loaded == [
        "focus_keyword",
        "topic",
        "featured_image_url",
        "featured_image_prompt",
        "featured_image_generated_url",
    ]
    assert worksheet.updated_rows == [
        (
            "1:1",
            [[
                "focus_keyword",
                "topic",
                "featured_image_url",
                "featured_image_prompt",
                "featured_image_generated_url",
            ]],
        )
    ]
    assert writer._logger.messages == [
        "Added missing Google Sheet headers: featured_image_prompt, featured_image_generated_url"
    ]


def test_google_sheet_writer_append_row_matches_headers_after_normalization():
    worksheet = _FakeWorksheet(
        [
            "Focus Keyword",
            "featured image prompt",
            "Ready",
        ]
    )
    writer = GoogleSheetWriter.__new__(GoogleSheetWriter)
    writer._worksheet = worksheet
    writer._logger = _FakeLogger()
    writer._ready_value = "ready"
    writer._headers = [
        "Focus Keyword",
        "featured image prompt",
        "Ready",
    ]

    writer.append_row(
        {
            "focus_keyword": "banana pudding truffles",
            "featured_image_prompt": "hero prompt",
        }
    )

    assert worksheet.appended_rows == [
        (
            ["banana pudding truffles", "hero prompt", "ready"],
            "USER_ENTERED",
            "A1",
        )
    ]


def test_google_sheet_writer_upsert_row_updates_existing_recipe_url_match():
    worksheet = _FakeWorksheet(
        [
            "Recipe Name",
            "Recipe URL",
            "featured_image_prompt",
            "Ready",
        ],
        rows=[
            [
                "Banana Pudding Truffles",
                "https://example.com/banana-truffles",
                "",
                "",
            ]
        ],
    )
    writer = GoogleSheetWriter.__new__(GoogleSheetWriter)
    writer._worksheet = worksheet
    writer._logger = _FakeLogger()
    writer._ready_value = "ready"
    writer._headers = [
        "Recipe Name",
        "Recipe URL",
        "featured_image_prompt",
        "Ready",
    ]

    action = writer.upsert_row(
        {
            "Recipe Name": "Banana Pudding Truffles",
            "Recipe URL": "https://example.com/banana-truffles",
            "featured_image_prompt": "hero prompt",
        }
    )

    assert action == "updated"
    assert worksheet.appended_rows == []
    assert worksheet.batch_updates == [
        (
            [
                {"range": "A2", "values": [["Banana Pudding Truffles"]]},
                {"range": "B2", "values": [["https://example.com/banana-truffles"]]},
                {"range": "C2", "values": [["hero prompt"]]},
                {"range": "D2", "values": [["ready"]]},
            ],
            "USER_ENTERED",
        )
    ]


def test_google_sheet_writer_upsert_row_appends_when_no_match_exists():
    worksheet = _FakeWorksheet(
        [
            "Recipe Name",
            "Recipe URL",
            "featured_image_prompt",
        ],
        rows=[
            [
                "Other Recipe",
                "https://example.com/other",
                "",
            ]
        ],
    )
    writer = GoogleSheetWriter.__new__(GoogleSheetWriter)
    writer._worksheet = worksheet
    writer._logger = _FakeLogger()
    writer._ready_value = "ready"
    writer._headers = [
        "Recipe Name",
        "Recipe URL",
        "featured_image_prompt",
    ]

    action = writer.upsert_row(
        {
            "Recipe Name": "Banana Pudding Truffles",
            "Recipe URL": "https://example.com/banana-truffles",
            "featured_image_prompt": "hero prompt",
        }
    )

    assert action == "appended"
    assert worksheet.batch_updates == []
    assert worksheet.appended_rows == [
        (
            [
                "Banana Pudding Truffles",
                "https://example.com/banana-truffles",
                "hero prompt",
            ],
            "USER_ENTERED",
            "A1",
        )
    ]
