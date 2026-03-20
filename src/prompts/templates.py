from __future__ import annotations

import re
from typing import List

from .models import PromptDraft
from .types import get_prompt_type_config, select_prompt_types


def build_template_prompt_drafts(
    *,
    dish_name: str,
    focus_keyword: str,
    style_anchor: str,
    seed: int,
    include_recipe_card: bool = False,
    include_ingredients: bool = False,
    include_pin: bool = False,
) -> List[PromptDraft]:
    prompt_types = select_prompt_types(
        include_recipe_card=include_recipe_card,
        include_ingredients=include_ingredients,
        include_pin=include_pin,
    )
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
    if prompt_type == "ingredients":
        return (
            f"{dish}, vertical Pinterest ingredients image, ingredients arranged neatly with balanced spacing "
            f"and clear visual separation, clean neutral marble or lightly textured surface, minimal clutter, "
            f"easy to read visually at a glance, attractive natural ingredient color contrast, "
            f"commercial food blog quality, {anchor}, no text, no watermark, no labels, no branding, "
            f"no packaging --ar 2:3 --seed {seed} --v 7"
        )
    if prompt_type == "pin":
        return (
            f"{dish}, full Pinterest recipe pin image designed for maximum mobile CTR, dominant hero food image "
            f"with a supporting inset or secondary food detail, clear collage hierarchy with hero food first, "
            f"clean title overlay area reserved for later text, premium Pinterest recipe graphic feel with highly "
            f"realistic food photography, vivid but natural appetizing color contrast, commercial food blog quality, "
            f"{anchor}, no text, no watermark, no labels, no branding, no packaging "
            f"--ar 2:3 --seed {seed} --v 7"
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
    if prompt_type == "ingredients":
        return "Near ingredients section"
    if prompt_type == "pin":
        return "Pinterest/social promotion asset"
    return "Recipe card area"


def _default_description(prompt_type: str) -> str:
    if prompt_type == "featured":
        return "Featured Pinterest recipe hero image"
    if prompt_type == "instructions_process":
        return "Hands preparing the recipe during a clear cooking step"
    if prompt_type == "serving":
        return "Vertical serving image with strong appetite appeal"
    if prompt_type == "ingredients":
        return "Vertical ingredients layout with clean spacing and strong readability"
    if prompt_type == "pin":
        return "Full Pinterest pin composition with a title overlay zone"
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
    if prompt_type == "ingredients":
        return {
            "alt_text": f"Ingredients for {keyword}",
            "filename": f"{slug}-ingredients.jpg",
            "caption": f"Ingredients for {dish}",
            "description": f"A vertical ingredients layout for {dish} with clear ingredient separation.",
        }
    if prompt_type == "pin":
        return {
            "alt_text": f"{keyword} Pinterest pin image",
            "filename": f"{slug}-pin.jpg",
            "caption": f"{dish} Pinterest pin",
            "description": f"A full Pinterest pin composition for {dish} with space reserved for title overlay.",
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
