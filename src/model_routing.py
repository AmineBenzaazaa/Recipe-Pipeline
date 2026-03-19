import os
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple


def _parse_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_int(value: str, default: int, minimum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return parsed if parsed >= minimum else minimum


def count_faq_items(faq_text: str) -> int:
    if not faq_text:
        return 0
    return len(re.findall(r"(?m)^\s*Q:\s+", faq_text))


def evaluate_row_quality(
    row: Dict[str, str],
    min_recipe_chars: int,
    min_faq_count: int,
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    recipe_text = (row.get("recipe_text") or "").strip()
    if len(recipe_text) < max(0, min_recipe_chars):
        reasons.append(f"recipe_text_too_short({len(recipe_text)}<{min_recipe_chars})")

    faq_count = count_faq_items(row.get("faq_text", ""))
    if faq_count < max(0, min_faq_count):
        reasons.append(f"faq_count_too_low({faq_count}<{min_faq_count})")

    return (len(reasons) == 0), reasons


@dataclass(frozen=True)
class ModelFallbackConfig:
    primary_model: str
    fallback_model: str
    enabled: bool
    min_recipe_chars: int
    min_faq_count: int


def resolve_model_fallback_config(
    *,
    current_model_name: str,
    env: Dict[str, str] | None = None,
) -> ModelFallbackConfig:
    data = env if env is not None else os.environ
    primary_model = (data.get("PRIMARY_MODEL_NAME") or current_model_name or "").strip()
    fallback_model = (data.get("FALLBACK_MODEL_NAME") or "").strip()
    enabled = _parse_bool(data.get("ENABLE_MODEL_FALLBACK", "false"))
    if not primary_model:
        primary_model = current_model_name
    if not fallback_model:
        enabled = False
    if fallback_model and fallback_model == primary_model:
        enabled = False
    min_recipe_chars = _parse_int(
        data.get("MODEL_FALLBACK_MIN_RECIPE_CHARS", "900"), default=900, minimum=0
    )
    min_faq_count = _parse_int(
        data.get("MODEL_FALLBACK_MIN_FAQ_COUNT", "4"), default=4, minimum=0
    )
    return ModelFallbackConfig(
        primary_model=primary_model,
        fallback_model=fallback_model,
        enabled=enabled,
        min_recipe_chars=min_recipe_chars,
        min_faq_count=min_faq_count,
    )
