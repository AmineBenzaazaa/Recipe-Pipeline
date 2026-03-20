from __future__ import annotations

import re
from typing import List

from .models import PromptDraft
from .types import PROMPT_TYPE_ORDER, get_prompt_type_config


def build_template_prompt_drafts(
    *,
    dish_name: str,
    focus_keyword: str,
    style_anchor: str,
    seed: int,
    include_recipe_card: bool = False,
) -> List[PromptDraft]:
    prompt_types = PROMPT_TYPE_ORDER if include_recipe_card else PROMPT_TYPE_ORDER[:3]
    drafts = []
    for prompt_type in prompt_types:
        config = get_prompt_type_config(prompt_type)
        drafts.append(
            PromptDraft(
                prompt_type=prompt_type,
                prompt_text=_build_prompt_text(
                    prompt_type=prompt_type,
                    dish_name=dish_name,
                    style_anchor=style_anchor,
                    seed=seed,
                ),
                placement=_default_placement(prompt_type),
                description=_default_description(prompt_type),
                seo_metadata=_default_seo_metadata(prompt_type, dish_name, focus_keyword),
                aspect_ratio=config.aspect_ratio,
            )
        )
    return drafts


def _build_prompt_text(
    *,
    prompt_type: str,
    dish_name: str,
    style_anchor: str,
    seed: int,
) -> str:
    dish = dish_name or "the dish"
    anchor = (style_anchor or "").strip()
    if prompt_type == "featured":
        return (
            f"{dish}, featured recipe hero image for Pinterest, tight food-first framing, "
            f"the finished dish dominating the frame, strong texture detail, glossy natural highlights, "
            f"clean appetizing color contrast, commercial food blog quality, bright natural lighting, "
            f"{anchor}, no text, no watermark, no labels, no branding, no packaging "
            f"--ar 3:2 --seed {seed} --v 7"
        )
    if prompt_type == "instructions_process":
        return (
            f"{dish}, recipe process image, hands actively preparing one clear cooking step, "
            f"vertical composition, tools and ingredients only as supporting context, visually clean "
            f"real-kitchen realism, attractive natural ingredient color, {anchor}, no text, no watermark, "
            f"no labels, no branding, no packaging --ar 2:3 --seed {seed} --v 7"
        )
    if prompt_type == "serving":
        return (
            f"{dish}, vertical serving image for Pinterest, food-forward plated composition, "
            f"plate or bowl visible but secondary, strong appetite appeal, rich natural color contrast, "
            f"clear texture separation, commercial food blog quality, {anchor}, no text, no watermark, "
            f"no labels, no branding, no packaging --ar 2:3 --seed {seed} --v 7"
        )
    return (
        f"{dish}, clean recipe card support image, natural food detail, simple composition, "
        f"{anchor}, no text, no watermark, no labels, no branding, no packaging "
        f"--ar 3:2 --seed {seed} --v 7"
    )


def _default_placement(prompt_type: str) -> str:
    if prompt_type == "featured":
        return "Top of article (before introduction)"
    if prompt_type == "instructions_process":
        return "Middle of article (in instructions section)"
    if prompt_type == "serving":
        return "Before serving section"
    return "Recipe card area"


def _default_description(prompt_type: str) -> str:
    if prompt_type == "featured":
        return "Featured Pinterest recipe hero image"
    if prompt_type == "instructions_process":
        return "Hands preparing the recipe during a clear cooking step"
    if prompt_type == "serving":
        return "Vertical serving image with strong appetite appeal"
    return "Clean recipe card support image"


def _default_seo_metadata(prompt_type: str, dish_name: str, focus_keyword: str) -> dict:
    dish = dish_name or focus_keyword or "recipe"
    keyword = focus_keyword or dish
    slug = _slugify(keyword)
    if prompt_type == "featured":
        return {
            "alt_text": f"{keyword} featured recipe hero image",
            "filename": f"{slug}-featured.jpg",
            "caption": f"{dish} ready to enjoy",
            "description": f"A featured hero image of {dish} with strong food-first composition.",
        }
    if prompt_type == "instructions_process":
        return {
            "alt_text": f"Preparing {keyword} step by step",
            "filename": f"{slug}-instructions-process.jpg",
            "caption": f"Preparing {dish}",
            "description": f"Hands actively preparing {dish} during one clear recipe step.",
        }
    if prompt_type == "serving":
        return {
            "alt_text": f"{keyword} serving image",
            "filename": f"{slug}-serving.jpg",
            "caption": f"Serve and enjoy {dish}",
            "description": f"A serving image of {dish} with strong appetite appeal.",
        }
    return {
        "alt_text": f"{keyword} recipe card image",
        "filename": f"{slug}-recipe-card.jpg",
        "caption": f"{dish} recipe card image",
        "description": f"A clean recipe card support image of {dish}.",
    }


def _slugify(text: str) -> str:
    lowered = (text or "").lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    return lowered.strip("-") or "recipe"
