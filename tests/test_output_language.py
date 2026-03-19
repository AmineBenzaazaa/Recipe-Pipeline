import logging

from src.config import Settings
from src.output_language import (
    localize_output_row,
    parse_site_language_map,
    resolve_output_language,
)


def test_parse_site_language_map_handles_multiple_delimiters():
    parsed = parse_site_language_map("gotujka.pl:pl, example.com=en;\nfoo.bar:de")
    assert parsed["gotujka.pl"] == "pl"
    assert parsed["example.com"] == "en"
    assert parsed["foo.bar"] == "de"


def test_parse_site_language_map_accepts_json_object():
    parsed = parse_site_language_map('{"Yumetry.com":"ES","www.Kochblog.de":"de"}')
    assert parsed["yumetry.com"] == "es"
    assert parsed["kochblog.de"] == "de"


def test_resolve_output_language_defaults_to_english():
    assert resolve_output_language(sheet_tab="") == "en"


def test_resolve_output_language_gotujka_defaults_to_polish():
    assert resolve_output_language(sheet_tab="Gotujka.pl") == "pl"


def test_resolve_output_language_explicit_override_wins():
    assert (
        resolve_output_language(
            sheet_tab="Gotujka.pl",
            explicit_language="en",
        )
        == "en"
    )


def test_resolve_output_language_uses_json_file_map(tmp_path):
    map_file = tmp_path / "site_language_map.json"
    map_file.write_text('{"yumetry.com":"es","www.kochblog.de":"de"}', encoding="utf-8")

    assert (
        resolve_output_language(
            sheet_tab="Yumetry.com",
            site_language_map_file=str(map_file),
            default_language="en",
        )
        == "es"
    )


def test_resolve_output_language_raw_map_overrides_file_map(tmp_path):
    map_file = tmp_path / "site_language_map.json"
    map_file.write_text('{"yumetry.com":"es"}', encoding="utf-8")

    assert (
        resolve_output_language(
            sheet_tab="yumetry.com",
            site_language_map_raw="yumetry.com:de",
            site_language_map_file=str(map_file),
            default_language="en",
        )
        == "de"
    )


def test_localize_output_row_skips_for_english():
    row = {
        "focus_keyword": "Banana bread",
        "topic": "Banana bread",
        "faq_text": "Q: What is banana bread?\nA: A sweet quick bread.",
        "recipe_text": "Title: Banana bread",
    }
    settings = Settings()
    logger = logging.getLogger("test")

    localized = localize_output_row(row, "en", settings, logger)
    assert localized == row


def test_localize_output_row_translates_with_openai(monkeypatch):
    row = {
        "focus_keyword": "Banana bread",
        "topic": "Banana bread",
        "faq_text": "Q: What is banana bread?\nA: A sweet quick bread.",
        "recipe_text": "Title: Banana bread",
    }
    settings = Settings(openai_api_key="sk-test")
    logger = logging.getLogger("test")

    def _fake_translate(_settings, _payload, _logger):
        return (
            '{"focus_keyword":"Chlebek bananowy","topic":"Chlebek bananowy",'
            '"faq_text":"P: Czym jest chlebek bananowy?\\nO: To slodki szybki wypiek.",'
            '"recipe_text":"Tytul: Chlebek bananowy"}'
        )

    monkeypatch.setattr("src.output_language._responses_create_text", _fake_translate)
    localized = localize_output_row(row, "pl", settings, logger)

    assert localized["focus_keyword"] == "Chlebek bananowy"
    assert localized["topic"] == "Chlebek bananowy"
    assert localized["faq_text"].startswith("P: Czym jest")
    assert localized["recipe_text"].startswith("Tytul:")
