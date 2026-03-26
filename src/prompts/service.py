from __future__ import annotations

import re
from typing import Dict, Iterable, List
from urllib.parse import urlparse

from ..midjourney_prompt_sanitizer import sanitize_midjourney_prompt
from ..prompt_rules import apply_pinterest_ctr_rules
from .models import PromptDraft, PromptSpec
from .templates import build_template_prompt_drafts
from .types import get_prompt_type_config, normalize_prompt_type


def build_template_prompt_bundle(
    *,
    dish_name: str,
    focus_keyword: str,
    style_anchor: str,
    seed: int,
    include_recipe_card: bool = False,
    include_ingredients: bool = False,
    include_pin: bool = False,
) -> List[PromptDraft]:
    return build_template_prompt_drafts(
        dish_name=dish_name,
        focus_keyword=focus_keyword,
        style_anchor=style_anchor,
        seed=seed,
        include_recipe_card=include_recipe_card,
        include_ingredients=include_ingredients,
        include_pin=include_pin,
    )


def build_template_prompt_payload(
    *,
    dish_name: str,
    focus_keyword: str,
    style_anchor: str,
    seed: int,
    include_recipe_card: bool = False,
    include_ingredients: bool = False,
    include_pin: bool = False,
) -> List[dict]:
    bundle = build_template_prompt_bundle(
        dish_name=dish_name,
        focus_keyword=focus_keyword,
        style_anchor=style_anchor,
        seed=seed,
        include_recipe_card=include_recipe_card,
        include_ingredients=include_ingredients,
        include_pin=include_pin,
    )
    return [item.to_payload() for item in bundle]


def build_prompt_bundle(
    *,
    dish_name: str,
    focus_keyword: str,
    style_anchor: str,
    seed: int,
    include_recipe_card: bool = False,
    include_ingredients: bool = False,
    include_pin: bool = False,
) -> List[PromptDraft]:
    return build_template_prompt_bundle(
        dish_name=dish_name,
        focus_keyword=focus_keyword,
        style_anchor=style_anchor,
        seed=seed,
        include_recipe_card=include_recipe_card,
        include_ingredients=include_ingredients,
        include_pin=include_pin,
    )


def build_prompt_payload(
    *,
    dish_name: str,
    focus_keyword: str,
    style_anchor: str,
    seed: int,
    include_recipe_card: bool = False,
    include_ingredients: bool = False,
    include_pin: bool = False,
) -> List[dict]:
    return build_template_prompt_payload(
        dish_name=dish_name,
        focus_keyword=focus_keyword,
        style_anchor=style_anchor,
        seed=seed,
        include_recipe_card=include_recipe_card,
        include_ingredients=include_ingredients,
        include_pin=include_pin,
    )


def finalize_prompt_text(
    prompt: str,
    prompt_type: str,
    *,
    reference_image_url: str = "",
    sanitize: bool = True,
    image_engine: str = "midjourney",
) -> str:
    prompt_map = finalize_prompt_map(
        {prompt_type: prompt},
        reference_image_url=reference_image_url,
        sanitize=sanitize,
        image_engine=image_engine,
    )
    return prompt_map.get(prompt_type, prompt)


def render_prompt_text_for_engine(
    prompt: str,
    prompt_type: str,
    *,
    image_engine: str = "midjourney",
) -> str:
    target = _normalize_prompt_target(image_engine)
    if target == "chatgpt":
        return _finalize_chatgpt_prompt(prompt, prompt_type)
    return sanitize_midjourney_prompt(prompt, normalize_prompt_type(prompt_type))


def finalize_prompt_map(
    prompt_map: Dict[str, str],
    *,
    reference_image_url: str = "",
    sanitize: bool = True,
    image_engine: str = "midjourney",
) -> Dict[str, str]:
    target = _normalize_prompt_target(image_engine)
    prefixed: Dict[str, str] = {}
    for prompt_type, prompt in prompt_map.items():
        if not isinstance(prompt, str) or not prompt.strip():
            prefixed[prompt_type] = prompt
            continue
        if target == "chatgpt":
            prefixed[prompt_type] = prompt
            continue
        prefixed[prompt_type] = _maybe_prefix_reference_image(
            prompt,
            prompt_type=prompt_type,
            reference_image_url=reference_image_url,
        )

    rewritten = apply_pinterest_ctr_rules(prefixed)
    if not sanitize:
        return rewritten

    finalized: Dict[str, str] = {}
    for prompt_type, prompt in rewritten.items():
        if not isinstance(prompt, str) or not prompt.strip():
            finalized[prompt_type] = prompt
            continue
        if target == "chatgpt":
            finalized[prompt_type] = render_prompt_text_for_engine(
                prompt,
                prompt_type,
                image_engine=image_engine,
            )
            continue
        finalized[prompt_type] = render_prompt_text_for_engine(
            prompt,
            prompt_type,
            image_engine=image_engine,
        )
    return finalized


def finalize_prompt_bundle(
    drafts: Iterable[PromptDraft],
    *,
    reference_image_url: str = "",
    sanitize: bool = True,
    image_engine: str = "midjourney",
) -> List[PromptSpec]:
    drafts = list(drafts)
    finalized_map = finalize_prompt_map(
        {draft.prompt_type: draft.prompt_text for draft in drafts},
        reference_image_url=reference_image_url,
        sanitize=sanitize,
        image_engine=image_engine,
    )
    return [
        PromptSpec(
            prompt_type=draft.prompt_type,
            raw_prompt_text=draft.prompt_text,
            finalized_prompt_text=finalized_map.get(draft.prompt_type, draft.prompt_text),
            placement=draft.placement,
            description=draft.description,
            seo_metadata=dict(draft.seo_metadata),
            aspect_ratio=draft.aspect_ratio,
        )
        for draft in drafts
    ]


def _maybe_prefix_reference_image(
    prompt: str,
    *,
    prompt_type: str,
    reference_image_url: str,
) -> str:
    config = get_prompt_type_config(prompt_type)
    if not config.reference_image_prefix:
        return prompt
    if not reference_image_url:
        return prompt
    cleaned_prompt = prompt.strip()
    cleaned_url = reference_image_url.strip()
    if not _looks_like_url(cleaned_url):
        return prompt
    if cleaned_prompt.startswith("http://") or cleaned_prompt.startswith("https://"):
        return prompt
    return f"{cleaned_url} {cleaned_prompt}"


def _looks_like_url(value: str) -> bool:
    parsed = urlparse((value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


_AR_RE = re.compile(r"(?<!\S)--ar\s+(\d{1,2}:\d{1,2})\b", re.I)
_MJ_PARAM_RE = re.compile(
    r"(?<!\S)--(?:ar|seed|v|q|quality|stylize|style|s|chaos|weird|iw)\b(?:\s+[^\s]+)?",
    re.I,
)
_MJ_TILE_RE = re.compile(r"(?<!\S)--tile\b", re.I)
_MJ_UNKNOWN_PARAM_RE = re.compile(r"(?<!\S)--\S+")
_ASPECT_RATIO_SENTENCE_RE = re.compile(
    r"(?:^|[.,;:]\s+)(?:horizontal|vertical|square)\s+composition,\s+\d{1,2}:\d{1,2}\s+aspect\s+ratio\.",
    re.I,
)


def _normalize_prompt_target(image_engine: str) -> str:
    engine = (image_engine or "").strip().lower()
    if engine in {"openai", "chatgpt"} or engine.startswith("gpt-image"):
        return "chatgpt"
    return "midjourney"


def _finalize_chatgpt_prompt(prompt: str, prompt_type: str) -> str:
    text = str(prompt).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""

    text = _strip_leading_reference_image(text)
    aspect_ratio = _last_match(_AR_RE, text) or get_prompt_type_config(prompt_type).aspect_ratio
    text = _MJ_PARAM_RE.sub("", text)
    text = _MJ_TILE_RE.sub("", text)
    text = _MJ_UNKNOWN_PARAM_RE.sub("", text)
    text = _ASPECT_RATIO_SENTENCE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" \t,;:-")
    if not text:
        text = "Professional food photography of the recipe"

    if text[-1] not in ".!?":
        text = f"{text}."
    return f"{text} {_aspect_ratio_sentence(prompt_type, aspect_ratio)}"


def _strip_leading_reference_image(prompt: str) -> str:
    first_token, _, remainder = prompt.partition(" ")
    if _looks_like_url(first_token):
        return remainder.strip()
    return prompt


def _last_match(pattern: re.Pattern[str], text: str) -> str:
    matches = list(pattern.finditer(text))
    if not matches:
        return ""
    return matches[-1].group(1)


def _aspect_ratio_sentence(prompt_type: str, aspect_ratio: str) -> str:
    orientation = get_prompt_type_config(prompt_type).orientation
    if orientation == "landscape":
        prefix = "Horizontal composition"
    elif orientation == "portrait":
        prefix = "Vertical composition"
    else:
        prefix = "Square composition"
    return f"{prefix}, {aspect_ratio} aspect ratio."
