from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTypeConfig:
    name: str
    orientation: str
    aspect_ratio: str
    pinterest_purpose: str
    aggressive_food_dominance: bool
    reference_image_prefix: bool
    rewrite_intensity: str


PROMPT_TYPE_ORDER = (
    "featured",
    "instructions_process",
    "serving",
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
        reference_image_prefix=True,
        rewrite_intensity="full",
    ),
    "instructions_process": PromptTypeConfig(
        name="instructions_process",
        orientation="portrait",
        aspect_ratio="2:3",
        pinterest_purpose="process image for recipe steps",
        aggressive_food_dominance=False,
        reference_image_prefix=False,
        rewrite_intensity="full",
    ),
    "serving": PromptTypeConfig(
        name="serving",
        orientation="portrait",
        aspect_ratio="2:3",
        pinterest_purpose="vertical serving image for Pinterest click appeal",
        aggressive_food_dominance=True,
        reference_image_prefix=True,
        rewrite_intensity="full",
    ),
    "wprm_recipecard": PromptTypeConfig(
        name="wprm_recipecard",
        orientation="landscape",
        aspect_ratio="3:2",
        pinterest_purpose="recipe card support image",
        aggressive_food_dominance=False,
        reference_image_prefix=True,
        rewrite_intensity="light",
    ),
}


def normalize_prompt_type(prompt_type: str) -> str:
    raw = (prompt_type or "").strip().lower()
    return PROMPT_TYPE_ALIASES.get(raw, raw)


def get_prompt_type_config(prompt_type: str) -> PromptTypeConfig:
    normalized = normalize_prompt_type(prompt_type)
    return PROMPT_TYPE_REGISTRY.get(normalized, PROMPT_TYPE_REGISTRY["featured"])


def prompt_type_aspect_ratio_map() -> dict[str, str]:
    mapping = {
        prompt_type: config.aspect_ratio
        for prompt_type, config in PROMPT_TYPE_REGISTRY.items()
    }
    for alias, canonical in PROMPT_TYPE_ALIASES.items():
        mapping[alias] = PROMPT_TYPE_REGISTRY[canonical].aspect_ratio
    return mapping
