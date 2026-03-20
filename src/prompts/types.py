from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTypeConfig:
    name: str
    orientation: str
    aspect_ratio: str
    pinterest_purpose: str
    aggressive_food_dominance: bool
    aggressive_ctr: bool
    reference_image_prefix: bool
    overlay_text_space: bool
    rewrite_intensity: str


CORE_PROMPT_TYPE_ORDER = (
    "featured",
    "instructions_process",
    "serving",
)

PROMPT_TYPE_ORDER = CORE_PROMPT_TYPE_ORDER + (
    "ingredients",
    "pin",
    "wprm_recipecard",
)

PROMPT_TYPE_ALIASES = {
    "instructions-process": "instructions_process",
    "wprm-recipecard": "wprm_recipecard",
}

PROMPT_TYPE_REGISTRY = {
    "featured": PromptTypeConfig(
        name="featured",
        orientation="landscape",
        aspect_ratio="3:2",
        pinterest_purpose="featured recipe hero image",
        aggressive_food_dominance=True,
        aggressive_ctr=True,
        reference_image_prefix=True,
        overlay_text_space=False,
        rewrite_intensity="full",
    ),
    "instructions_process": PromptTypeConfig(
        name="instructions_process",
        orientation="portrait",
        aspect_ratio="2:3",
        pinterest_purpose="process image for recipe steps",
        aggressive_food_dominance=False,
        aggressive_ctr=True,
        reference_image_prefix=False,
        overlay_text_space=False,
        rewrite_intensity="full",
    ),
    "serving": PromptTypeConfig(
        name="serving",
        orientation="portrait",
        aspect_ratio="2:3",
        pinterest_purpose="vertical serving image for Pinterest click appeal",
        aggressive_food_dominance=True,
        aggressive_ctr=True,
        reference_image_prefix=True,
        overlay_text_space=False,
        rewrite_intensity="full",
    ),
    "ingredients": PromptTypeConfig(
        name="ingredients",
        orientation="portrait",
        aspect_ratio="2:3",
        pinterest_purpose="vertical ingredients layout for Pinterest clarity",
        aggressive_food_dominance=False,
        aggressive_ctr=True,
        reference_image_prefix=False,
        overlay_text_space=False,
        rewrite_intensity="full",
    ),
    "pin": PromptTypeConfig(
        name="pin",
        orientation="portrait",
        aspect_ratio="2:3",
        pinterest_purpose="full Pinterest recipe pin graphic",
        aggressive_food_dominance=True,
        aggressive_ctr=True,
        reference_image_prefix=False,
        overlay_text_space=True,
        rewrite_intensity="full",
    ),
    "wprm_recipecard": PromptTypeConfig(
        name="wprm_recipecard",
        orientation="landscape",
        aspect_ratio="3:2",
        pinterest_purpose="recipe card support image",
        aggressive_food_dominance=False,
        aggressive_ctr=False,
        reference_image_prefix=True,
        overlay_text_space=False,
        rewrite_intensity="light",
    ),
}


def normalize_prompt_type(prompt_type: str) -> str:
    raw = (prompt_type or "").strip().lower()
    return PROMPT_TYPE_ALIASES.get(raw, raw)


def get_prompt_type_config(prompt_type: str) -> PromptTypeConfig:
    normalized = normalize_prompt_type(prompt_type)
    return PROMPT_TYPE_REGISTRY.get(normalized, PROMPT_TYPE_REGISTRY["featured"])


def select_prompt_types(
    *,
    include_recipe_card: bool = False,
    include_ingredients: bool = False,
    include_pin: bool = False,
) -> tuple[str, ...]:
    prompt_types = list(CORE_PROMPT_TYPE_ORDER)
    if include_ingredients:
        prompt_types.append("ingredients")
    if include_pin:
        prompt_types.append("pin")
    if include_recipe_card:
        prompt_types.append("wprm_recipecard")
    return tuple(prompt_types)


def prompt_type_aspect_ratio_map() -> dict[str, str]:
    mapping = {
        prompt_type: config.aspect_ratio
        for prompt_type, config in PROMPT_TYPE_REGISTRY.items()
    }
    for alias, canonical in PROMPT_TYPE_ALIASES.items():
        mapping[alias] = PROMPT_TYPE_REGISTRY[canonical].aspect_ratio
    return mapping
