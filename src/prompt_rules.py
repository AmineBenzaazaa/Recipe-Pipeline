from __future__ import annotations

import re
from html import unescape
from typing import Dict
from urllib.parse import urlparse

from .prompts.types import get_prompt_type_config, normalize_prompt_type

_NEGATIVE_TOKENS = (
    r"\bno text(?: overlay)?\b",
    r"\bno words\b",
    r"\bno letters\b",
    r"\bno typography\b",
    r"\bno watermark\b",
    r"\bno logos?\b",
    r"\bno branding\b",
    r"\bno labels?\b",
    r"\bno writing\b",
    r"\bno packaging\b",
    r"\bno cgi(?: look)?\b",
    r"\bno synthetic texture\b",
)

_FOOD_SAFETY_TOKENS = (
    r"\bno pork\b",
    r"\bno bacon\b",
    r"\bno ham\b",
    r"\bno lard\b",
    r"\bno gelatin\b",
    r"\bno alcohol\b",
    r"\bavoid any pork\b",
    r"\bavoid any bacon\b",
    r"\bavoid any ham\b",
    r"\bavoid any lard\b",
    r"\bavoid any gelatin\b",
    r"\bavoid any alcohol\b",
)

_AR_RE = re.compile(r"(?<!\S)--ar\s+(\d{1,2}:\d{1,2})\b", re.I)
_SEED_RE = re.compile(r"(?<!\S)--seed\s+(\d{1,12})\b", re.I)
_VERSION_RE = re.compile(r"(?<!\S)--v\s+([0-9]+(?:\.[0-9]+)?)\b", re.I)
_STYLE_RE = re.compile(r"(?<!\S)--style\s+([a-zA-Z][a-zA-Z0-9_-]*)\b", re.I)
_STYLIZE_RE = re.compile(r"(?<!\S)--(?:s|stylize)\s+(\d{1,4})\b", re.I)
_QUALITY_RE = re.compile(r"(?<!\S)--(?:q|quality)\s+([0-9]+(?:\.[0-9]+)?)\b", re.I)

_NEGATIVE_CLAUSE = (
    "no text, no watermark, no labels, no branding, no packaging, no CGI, no synthetic texture"
)
_FOOD_SAFETY_CLAUSE = "no pork, no bacon, no ham, no lard, no gelatin, no alcohol"

_LEGACY_PATTERNS = (
    r"\bexact same batch as the featured image\.?",
    r"\bfocus on the recipe\.?",
    r"\bPinterest viral(?: dessert/recipe hero styling| recipe style| close-up hero| plated serving hero)?\b",
    r"\bsame visual style and batch as featured image for consistency\b",
    r"\bsame batch as featured image\b",
    r"\bsame lighting family as featured image\b",
    r"\brecipe-locked\b",
    r"\bDSLR 85mm lens(?: look| aesthetic)?\b",
    r"\bclean composition with negative space for text overlay\b",
)

_LEADING_PHRASE_REPLACEMENTS = (
    (r"^\s*professional food photography of\s+", ""),
    (r"^\s*ultra realistic\s+", ""),
    (r"\bcommercial bakery-style food photography\b", "commercial food blog photography"),
    (r"\binstructions-only process photo\b", "recipe process photo"),
)

_DESSERT_HINTS = (
    "dessert",
    "cookie",
    "cookies",
    "cake",
    "cupcake",
    "brownie",
    "bar",
    "frosting",
    "icing",
    "sprinkle",
    "marshmallow",
    "candy",
    "chocolate",
    "cheesecake",
    "donut",
    "muffin",
    "pie",
    "tart",
)

_PASTEL_HINTS = (
    "easter",
    "spring",
    "pastel",
    "lemon",
    "strawberry",
    "raspberry",
    "berry",
    "berries",
    "blueberry",
    "peach",
)

_BAKED_HINTS = (
    "baked",
    "bake",
    "bread",
    "roll",
    "bun",
    "muffin",
    "biscuit",
    "cookie",
    "brownie",
    "cake",
    "cobbler",
    "granola",
)

_SAVORY_HINTS = (
    "salad",
    "soup",
    "stew",
    "pasta",
    "chicken",
    "beef",
    "turkey",
    "rice",
    "vegetable",
    "garlic",
    "herb",
    "roast",
    "sandwich",
)


def apply_pinterest_ctr_rules(prompt_map: dict[str, str]) -> dict[str, str]:
    updated: Dict[str, str] = {}
    for prompt_type, prompt in prompt_map.items():
        if not isinstance(prompt, str) or not prompt.strip():
            updated[prompt_type] = prompt
            continue
        updated[prompt_type] = _apply_prompt_rules(prompt, prompt_type)
    return updated


def _apply_prompt_rules(prompt: str, prompt_type: str) -> str:
    reference_url, body, params = _split_prompt(prompt)
    canonical_type = normalize_prompt_type(prompt_type)
    config = get_prompt_type_config(prompt_type)
    had_food_safety = _has_food_safety_clause(body)

    body = _strip_params(body)
    body = _clean_legacy_body(body)
    body = _remove_negative_clauses(body)
    body = _remove_food_safety_clauses(body)
    body = _normalize_whitespace(body)

    clauses = []
    if body:
        clauses.append(body)

    if canonical_type == "featured":
        clauses.extend(
            [
                "featured Pinterest recipe hero image",
                "tight food-first framing with the dish filling about 80 percent of the frame",
                "strong visual hierarchy with the food clearly dominating the composition",
                "crisp texture detail with toppings, crumb, frosting, filling, or sauce clearly defined",
            ]
        )
    elif canonical_type == "serving":
        clauses.extend(
            [
                "vertical Pinterest serving image",
                "food-forward composition with the plated food filling roughly 75 to 85 percent of the frame",
                "plate or bowl visible but secondary to the food",
                "show a broken, lifted, or cut-open element when it makes the serving look more craveable",
            ]
        )
    elif canonical_type == "instructions_process":
        clauses.extend(
            [
                "vertical Pinterest process image",
                "hands actively performing one clear cooking or baking step",
                "the action should read instantly at mobile size",
                "ingredients and tools stay as supporting context around the action",
                "clean but slightly imperfect real-kitchen realism",
            ]
        )
    elif canonical_type == "wprm_recipecard":
        clauses.append("clean food-forward recipe card image with clear visibility of the finished dish")

    clauses.append(_color_clause(canonical_type, body))

    if config.rewrite_intensity != "light":
        clauses.append(
            "commercial food blog quality, highly realistic, natural appetizing lighting, visually striking but believable"
        )
    else:
        clauses.append("natural-looking food detail, clean composition")

    clauses.append(_NEGATIVE_CLAUSE)
    if had_food_safety:
        clauses.append(_FOOD_SAFETY_CLAUSE)

    final_body = _join_clauses(clauses)
    suffix = _build_suffix(canonical_type, params)

    result = final_body
    if reference_url:
        result = f"{reference_url} {result}".strip()
    if suffix:
        result = f"{result} {suffix}".strip()
    return result

def _split_prompt(prompt: str) -> tuple[str, str, dict[str, str]]:
    text = _normalize_whitespace(unescape(str(prompt)))
    reference_url = ""
    first_token, _, remainder = text.partition(" ")
    if _looks_like_url(first_token):
        reference_url = first_token
        text = remainder.strip()
    params = _collect_params(text)
    return reference_url, text, params


def _looks_like_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _last_match(pattern: re.Pattern[str], text: str) -> str:
    matches = list(pattern.finditer(text))
    if not matches:
        return ""
    return matches[-1].group(1)


def _collect_params(text: str) -> dict[str, str]:
    return {
        "ar": _last_match(_AR_RE, text),
        "seed": _last_match(_SEED_RE, text),
        "version": _last_match(_VERSION_RE, text),
        "style": _last_match(_STYLE_RE, text),
        "stylize": _last_match(_STYLIZE_RE, text),
        "quality": _last_match(_QUALITY_RE, text),
    }


def _strip_params(text: str) -> str:
    cleaned = re.sub(
        r"(?<!\S)--(?:ar|seed|v|q|quality|stylize|style|s|chaos|weird|iw)\b(?:\s+[^\s]+)?",
        "",
        text,
        flags=re.I,
    )
    cleaned = re.sub(r"(?<!\S)--tile\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"(?<!\S)--\S+", "", cleaned)
    return cleaned


def _clean_legacy_body(text: str) -> str:
    cleaned = text
    for pattern in _LEGACY_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.I)
    for pattern, replacement in _LEADING_PHRASE_REPLACEMENTS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.I)
    cleaned = re.sub(r"\bhero shot of the finished recipe\b", "finished recipe hero image", cleaned, flags=re.I)
    cleaned = re.sub(r"\bappetizing presentation\b", "appetizing food presentation", cleaned, flags=re.I)
    cleaned = re.sub(r"\brestaurant-quality presentation\b", "restaurant-quality food presentation", cleaned, flags=re.I)
    cleaned = re.sub(r"\bhigh resolution\b", "high detail", cleaned, flags=re.I)
    cleaned = re.sub(r"\b8k\b", "high detail", cleaned, flags=re.I)
    return cleaned


def _remove_negative_clauses(text: str) -> str:
    cleaned = text
    for pattern in _NEGATIVE_TOKENS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.I)
    return cleaned


def _remove_food_safety_clauses(text: str) -> str:
    cleaned = text
    for pattern in _FOOD_SAFETY_TOKENS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.I)
    return cleaned


def _has_food_safety_clause(text: str) -> bool:
    source = text or ""
    return any(re.search(pattern, source, flags=re.I) for pattern in _FOOD_SAFETY_TOKENS)


def _color_clause(prompt_type: str, body: str) -> str:
    lowered = (body or "").lower()
    if any(token in lowered for token in _PASTEL_HINTS) and any(token in lowered for token in _DESSERT_HINTS):
        return (
            "bright, appetizing, natural-looking pastel color with vivid but believable dessert accents and clean topping color separation"
        )
    if any(token in lowered for token in _BAKED_HINTS):
        return (
            "richer warm golden tones, glossy natural highlights, and clear color contrast between crust, crumb, frosting, and toppings"
        )
    if any(token in lowered for token in ("fruit", "berry", "berries", "strawberry", "blueberry", "raspberry", "citrus", "lemon", "orange")):
        return (
            "bright appetizing natural color with clean fruit and topping contrast and more visually striking Pinterest-friendly color separation"
        )
    if any(token in lowered for token in _DESSERT_HINTS):
        return (
            "bright appetizing dessert color, glossy natural highlights, and clear color contrast between crumb, filling, frosting, and toppings"
        )
    if any(token in lowered for token in _SAVORY_HINTS):
        if prompt_type == "instructions_process":
            return "clean, lively ingredient color with believable contrast and fresh supporting accents"
        return "clean appetizing natural color contrast with fresh garnish accents and richer warm highlights where appropriate"
    if prompt_type == "instructions_process":
        return "attractive natural ingredient color with lively but believable contrast"
    return "strong natural-looking color contrast with clean, scroll-stopping but believable food presentation"


def _join_clauses(clauses: list[str]) -> str:
    seen = set()
    ordered = []
    for clause in clauses:
        cleaned = _normalize_clause(clause)
        if not cleaned:
            continue
        normalized_key = re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip()
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        ordered.append(cleaned)
    joined = ", ".join(ordered)
    joined = re.sub(r"\s*,\s*,+", ", ", joined)
    joined = re.sub(r"\s+", " ", joined)
    return joined.strip(" ,.-")


def _normalize_clause(value: str) -> str:
    cleaned = _normalize_whitespace(value)
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    cleaned = re.sub(r"\s*\.\s*", ". ", cleaned)
    cleaned = cleaned.strip(" ,.-")
    return cleaned


def _normalize_whitespace(text: str) -> str:
    cleaned = (text or "").replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _build_suffix(prompt_type: str, params: dict[str, str]) -> str:
    parts = []
    current_ar = params.get("ar", "")
    config = get_prompt_type_config(prompt_type)
    canonical_ar = config.aspect_ratio
    if config.rewrite_intensity == "light":
        ar_value = current_ar or canonical_ar
    else:
        ar_value = canonical_ar or current_ar
    if ar_value:
        parts.append(f"--ar {ar_value}")
    if params.get("seed"):
        parts.append(f"--seed {params['seed']}")
    if params.get("version"):
        parts.append(f"--v {params['version']}")
    if params.get("style"):
        parts.append(f"--style {params['style']}")
    if params.get("stylize"):
        parts.append(f"--s {params['stylize']}")
    if params.get("quality"):
        parts.append(f"--q {params['quality']}")
    return " ".join(parts)
