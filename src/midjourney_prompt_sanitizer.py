import re
from html import unescape

from .prompts.types import prompt_type_aspect_ratio_map
DEFAULT_AR_BY_TYPE = prompt_type_aspect_ratio_map()

_AR_RE = re.compile(r"(?<!\S)--ar\s+(\d{1,2}:\d{1,2})\b", re.I)
_SEED_RE = re.compile(r"(?<!\S)--seed\s+(\d{1,12})\b", re.I)
_VERSION_RE = re.compile(r"(?<!\S)--v\s+([0-9]+(?:\.[0-9]+)?)\b", re.I)
_STYLE_RE = re.compile(r"(?<!\S)--style\s+([a-zA-Z][a-zA-Z0-9_-]*)\b", re.I)
_STYLIZE_RE = re.compile(r"(?<!\S)--(?:s|stylize)\s+(\d{1,4})\b", re.I)
_QUALITY_RE = re.compile(r"(?<!\S)--(?:q|quality)\s+([0-9]+(?:\.[0-9]+)?)\b", re.I)


def _last_match(pattern: re.Pattern[str], text: str) -> str:
    matches = list(pattern.finditer(text))
    if not matches:
        return ""
    return matches[-1].group(1)


def sanitize_midjourney_prompt(prompt: str, prompt_type: str = "featured") -> str:
    """Normalize prompt text to Midjourney-safe syntax.

    The sanitizer keeps natural-language body text, strips malformed/unsupported
    parameters, and re-attaches a safe parameter suffix:
    `--ar <ratio> [--seed <int>] --v <version>`.
    """
    if not prompt:
        return ""

    text = unescape(str(prompt))
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"`{1,3}", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""

    text = re.sub(
        r"^(?:prompt|image prompt|featured(?: image)?|instructions(?:[_\s-]*process)?(?: image)?|"
        r"serving(?: image)?|wprm(?:[_\s-]*recipecard)?(?: image)?)\s*:\s*",
        "",
        text,
        flags=re.I,
    )

    ar_value = _last_match(_AR_RE, text)
    seed_value = _last_match(_SEED_RE, text)
    version_value = _last_match(_VERSION_RE, text) or "7"
    style_value = _last_match(_STYLE_RE, text).lower()
    stylize_value = _last_match(_STYLIZE_RE, text)
    quality_value = _last_match(_QUALITY_RE, text)

    # Remove all known MJ params from body text. We later rebuild a safe suffix.
    text = re.sub(
        r"(?<!\S)--(?:ar|seed|v|q|quality|stylize|style|s|chaos|weird|iw)\b(?:\s+[^\s]+)?",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"(?<!\S)--tile\b", "", text, flags=re.I)

    # Remove any unknown or malformed param fragments (e.g. "--," or "--foo").
    text = re.sub(r"(?<!\S)--\S+", "", text)

    # Strip bullet/list noise and accidental prefixed punctuation.
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"^\s*[\-\*\u2022]+\s*", "", text)
        text = re.sub(r"^\s*\d+\s*[\)\.\-:]\s*", "", text)
        text = re.sub(r"^\s*[a-zA-Z]\)\s*", "", text)
        text = re.sub(r"^\s*[,:;]+\s*", "", text)
    text = re.sub(r"(?<!\S)-,\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" \t,;:-")
    text = re.sub(r'^[\'"]+|[\'"]+$', "", text).strip()

    if not text:
        text = "Professional food photography of the recipe"

    ar_value = ar_value or DEFAULT_AR_BY_TYPE.get(prompt_type, "1:1")
    if style_value != "raw":
        style_value = ""
    if quality_value not in {"0.25", "0.5", "1", "2"}:
        quality_value = ""

    parts = [text, f"--ar {ar_value}"]
    if seed_value:
        parts.append(f"--seed {seed_value}")
    parts.append(f"--v {version_value}")
    if style_value:
        parts.append(f"--style {style_value}")
    if stylize_value:
        parts.append(f"--s {stylize_value}")
    if quality_value:
        parts.append(f"--q {quality_value}")
    return " ".join(parts)
