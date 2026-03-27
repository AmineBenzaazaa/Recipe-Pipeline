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
            f"{dish}, single vertical recipe process collage divided into 6 equal panels in a 2-column 3-row grid, "
            "each panel numbered 1 to 6 with a small bold number in the top corner, all panels locked to identical "
            "soft warm natural window light, a recipe-matched pastel color tone, and a neutral white marble background, "
            "show only the cooking method steps from prep through the last active step before completion, never show "
            "serving, plating, finished dish presentation, or the final product. "
            "Panel 1: ingredient and mise en place setup with recipe-specific raw ingredients, organized tools, prep "
            "bowls, measuring tools, and pans on marble, no hands. "
            "Panel 2: first active manual technique with one active hand performing the first key recipe step, named "
            "vessels with sizes and materials, recipe-matched scatter, and shallow depth of field. "
            "Panel 3: passive result of a baking, resting, chilling, or cooling stage with recipe-specific texture "
            "changes visible, no hands. "
            "Panel 4: second active mixing or combining step with one active hand and a second hand only if needed to "
            "steady the bowl, named vessels with sizes and materials, realistic scatter, and shallow depth of field. "
            "Panel 5: transfer or pour step with only a minimal hand visible on the bowl, jug, tray, or pan edge, "
            "named vessels with sizes and materials, realistic scatter, and shallow depth of field. "
            "Panel 6: final oven placement or equivalent last active pre-completion step with no hands visible. "
            "Every panel must describe food color, texture, slight imperfections, and realistic surface scatter "
            "matching the recipe such as flour, crumbs, zest, sugar grains, herbs, or smears, and must explicitly "
            "state the hand presence or explicit no hands. "
            "Commercial food blog photography, professional food photography, soft warm natural window light with "
            "warm golden highlights, bright appetizing pastel tone keyed to the recipe's dominant color, shallow "
            "depth of field DSLR 85mm aesthetic, neutral white marble surface, slightly imperfect lived-in kitchen "
            f"realism, emphasize the visual contrast between the recipe's main components, {anchor}, no text, no "
            "watermark, no labels, no branding, no packaging, no CGI, no synthetic texture, vertical 2:3 aspect "
            f"ratio --ar 2:3 --seed {seed} --v 7"
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
        return "Six-panel instructions collage showing the key recipe steps before completion"
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
            "alt_text": f"Six-panel process collage for preparing {keyword}",
            "filename": f"{slug}-instructions-process.jpg",
            "caption": f"Step-by-step {dish} process collage",
            "description": f"A six-panel process collage showing the key active recipe steps for {dish} before completion.",
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
