import json
import logging
import os
import re
from pathlib import Path
from typing import Dict
from urllib.parse import urlparse

from .config import Settings


DEFAULT_OUTPUT_LANGUAGE = "en"
DEFAULT_SITE_LANGUAGE_MAP = {
    "gotujka.pl": "pl",
}
DEFAULT_SITE_LANGUAGE_MAP_FILE = (
    Path(__file__).resolve().parent.parent / ".secrets" / "site_language_map.json"
)
TRANSLATABLE_ROW_FIELDS = ("focus_keyword", "topic", "faq_text", "recipe_text")

_LANG_ALIAS_TO_CODE = {
    "english": "en",
    "german": "de",
    "deutsch": "de",
    "spanish": "es",
    "espanol": "es",
    "español": "es",
    "french": "fr",
    "francais": "fr",
    "français": "fr",
    "italian": "it",
    "portuguese": "pt",
    "polish": "pl",
    "turkish": "tr",
    "arabic": "ar",
    "hindi": "hi",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh",
}

_LANG_NAME_BY_CODE = {
    "en": "English",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "sv": "Swedish",
    "no": "Norwegian",
    "da": "Danish",
    "fi": "Finnish",
    "cs": "Czech",
    "pl": "Polish",
    "ro": "Romanian",
    "hu": "Hungarian",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ru": "Russian",
    "ar": "Arabic",
    "he": "Hebrew",
    "hi": "Hindi",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "ms": "Malay",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
}


def _responses_create_text(
    settings: Settings, payload: dict, logger: logging.Logger
) -> str:
    from .openai_client import responses_create_text as _call

    return _call(settings, payload, logger)


def _normalize_language_code(value: str) -> str:
    cleaned = (value or "").strip().lower().replace("_", "-")
    if not cleaned:
        return ""
    if cleaned in _LANG_ALIAS_TO_CODE:
        return _LANG_ALIAS_TO_CODE[cleaned]
    primary = cleaned.split("-", 1)[0]
    if primary in _LANG_ALIAS_TO_CODE:
        return _LANG_ALIAS_TO_CODE[primary]
    return primary or ""


def _normalize_site_key(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if not cleaned:
        return ""
    if "://" in cleaned:
        parsed = urlparse(cleaned)
        cleaned = parsed.netloc or parsed.path or ""
    cleaned = cleaned.strip().strip("/")
    if cleaned.startswith("www."):
        cleaned = cleaned[4:]
    return cleaned


def _normalize_site_language_mapping(mapping: dict) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for raw_site, raw_lang in mapping.items():
        site_key = _normalize_site_key(str(raw_site or ""))
        lang_code = _normalize_language_code(str(raw_lang or ""))
        if site_key and lang_code:
            normalized[site_key] = lang_code
    return normalized


def parse_site_language_map(raw: str) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    if not raw:
        return parsed
    maybe_json = raw.strip()
    if maybe_json.startswith("{") and maybe_json.endswith("}"):
        try:
            json_mapping = json.loads(maybe_json)
        except json.JSONDecodeError:
            json_mapping = None
        if isinstance(json_mapping, dict):
            return _normalize_site_language_mapping(json_mapping)
    chunks = re.split(r"[,\n;]+", raw)
    for chunk in chunks:
        item = chunk.strip()
        if not item:
            continue
        if ":" in item:
            site, lang = item.split(":", 1)
        elif "=" in item:
            site, lang = item.split("=", 1)
        else:
            continue
        site_key = _normalize_site_key(site)
        lang_code = _normalize_language_code(lang)
        if site_key and lang_code:
            parsed[site_key] = lang_code
    return parsed


def load_site_language_map_from_file(path: str = "") -> Dict[str, str]:
    cleaned_path = (path or "").strip()
    target_path = (
        Path(cleaned_path).expanduser()
        if cleaned_path
        else DEFAULT_SITE_LANGUAGE_MAP_FILE
    )
    if not target_path.exists() or not target_path.is_file():
        return {}
    try:
        raw = target_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return parse_site_language_map(raw)
    if not isinstance(parsed, dict):
        return {}
    return _normalize_site_language_mapping(parsed)


def resolve_output_language(
    *,
    sheet_tab: str,
    explicit_language: str = "",
    site_language_map_raw: str = "",
    site_language_map_file: str = "",
    default_language: str = DEFAULT_OUTPUT_LANGUAGE,
) -> str:
    explicit = _normalize_language_code(explicit_language)
    if explicit:
        return explicit

    default_lang = _normalize_language_code(default_language) or DEFAULT_OUTPUT_LANGUAGE
    site_lang_map = {
        **DEFAULT_SITE_LANGUAGE_MAP,
        **load_site_language_map_from_file(site_language_map_file),
        **parse_site_language_map(site_language_map_raw),
    }
    site_key = _normalize_site_key(sheet_tab)
    if not site_key:
        return default_lang

    if site_key in site_lang_map:
        return site_lang_map[site_key]

    # Match custom map keys against tab suffixes (e.g., subdomain.example.com -> example.com)
    for mapped_site, mapped_lang in site_lang_map.items():
        if site_key.endswith(f".{mapped_site}"):
            return mapped_lang

    # Practical fallback for country domains.
    if site_key.endswith(".pl"):
        return "pl"

    return default_lang


def resolve_output_language_from_env(sheet_tab: str) -> str:
    return resolve_output_language(
        sheet_tab=sheet_tab,
        explicit_language=os.getenv("OUTPUT_LANGUAGE", ""),
        site_language_map_raw=os.getenv("SITE_LANGUAGE_MAP", ""),
        site_language_map_file=os.getenv("SITE_LANGUAGE_MAP_FILE", ""),
        default_language=os.getenv("DEFAULT_OUTPUT_LANGUAGE", DEFAULT_OUTPUT_LANGUAGE),
    )


def _extract_json_object(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    if not text:
        return ""
    if text.startswith("{") and text.endswith("}"):
        return text
    match = re.search(r"\{.*\}", text, flags=re.S)
    return match.group(0) if match else ""


def _translate_values_with_openai(
    values: Dict[str, str],
    target_language_code: str,
    settings: Settings,
    logger: logging.Logger,
) -> Dict[str, str]:
    language_name = _LANG_NAME_BY_CODE.get(target_language_code, target_language_code)
    payload = {
        "model": settings.model_name,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a careful translator for recipe content. "
                    "Return JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Translate each JSON value to {language_name} ({target_language_code}).\n"
                    "Rules:\n"
                    "- Keep exactly the same JSON keys.\n"
                    "- If a value is already in the target language, return it unchanged.\n"
                    "- Output must be fully in the target language (except unavoidable proper names/brands).\n"
                    "- Preserve line breaks, list numbering, punctuation, and units.\n"
                    "- Do not add or remove facts.\n"
                    "- Return ONLY a JSON object.\n\n"
                    f"Input JSON:\n{json.dumps(values, ensure_ascii=False)}"
                ),
            },
        ],
        "temperature": 0.0,
        "max_output_tokens": 5000,
    }

    output_text = _responses_create_text(settings, payload, logger)
    json_text = _extract_json_object(output_text)
    if not json_text:
        raise ValueError("translation response did not include JSON")

    parsed = json.loads(json_text)
    if not isinstance(parsed, dict):
        raise ValueError("translation response was not a JSON object")

    translated: Dict[str, str] = {}
    for key, original_value in values.items():
        candidate = parsed.get(key)
        if isinstance(candidate, str) and candidate.strip():
            translated[key] = candidate
        else:
            translated[key] = original_value
    return translated


def localize_output_row(
    row: dict,
    target_language_code: str,
    settings: Settings,
    logger: logging.Logger,
) -> dict:
    target = _normalize_language_code(target_language_code)
    if not target:
        return row

    fields_to_translate: Dict[str, str] = {}
    for key in TRANSLATABLE_ROW_FIELDS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            fields_to_translate[key] = value

    if not fields_to_translate:
        return row

    if not settings.openai_api_key:
        logger.warning(
            "Output language is '%s' but OPENAI_API_KEY is not set; keeping original text.",
            target,
        )
        return row

    try:
        translated = _translate_values_with_openai(
            fields_to_translate,
            target,
            settings,
            logger,
        )
    except Exception as exc:
        logger.warning(
            "Failed to localize output row to '%s': %s. Keeping original text.",
            target,
            exc,
        )
        return row

    updated = dict(row)
    updated.update(translated)
    return updated
