from __future__ import annotations

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
) -> str:
    prompt_map = finalize_prompt_map(
        {prompt_type: prompt},
        reference_image_url=reference_image_url,
        sanitize=sanitize,
    )
    return prompt_map.get(prompt_type, prompt)


def finalize_prompt_map(
    prompt_map: Dict[str, str],
    *,
    reference_image_url: str = "",
    sanitize: bool = True,
) -> Dict[str, str]:
    prefixed: Dict[str, str] = {}
    for prompt_type, prompt in prompt_map.items():
        if not isinstance(prompt, str) or not prompt.strip():
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
        finalized[prompt_type] = sanitize_midjourney_prompt(
            prompt,
            normalize_prompt_type(prompt_type),
        )
    return finalized


def finalize_prompt_bundle(
    drafts: Iterable[PromptDraft],
    *,
    reference_image_url: str = "",
    sanitize: bool = True,
) -> List[PromptSpec]:
    drafts = list(drafts)
    finalized_map = finalize_prompt_map(
        {draft.prompt_type: draft.prompt_text for draft in drafts},
        reference_image_url=reference_image_url,
        sanitize=sanitize,
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
