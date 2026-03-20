"""
GPT-assisted prompt generation with a shared Pinterest-first template service.

This module still performs GPT prompt analysis, while shared template composition
and prompt finalization now live in the prompt service to reduce drift.
"""

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from .config import DEFAULT_STYLE_ANCHOR, Settings
from .midjourney_prompt_sanitizer import sanitize_midjourney_prompt
from .models import Recipe
from .openai_client import responses_create_text
from .prompts.service import build_template_prompt_payload


def generate_random_seed() -> int:
    """Generate a random seed for Midjourney consistency."""
    import random
    return random.randint(1000000000, 9999999999)


def _inject_no_text_exclusions(prompt_text: str) -> str:
    """
    Ensure the prompt contains the no-text / no-brand exclusions inserted BEFORE --ar.
    Keeps diffs minimal by only touching prompts missing the exclusions.
    """
    if not prompt_text:
        return prompt_text

    prompt = prompt_text
    if "no text" not in prompt.lower():
        exclusions = "no text no words no letters no typography no watermark no logo no branding no labels"
        if " --ar" in prompt:
            prompt = prompt.replace(" --ar", f", {exclusions} --ar")
        else:
            prompt = f"{prompt}, {exclusions}"

    if not re.search(r"\s--v\s+[\d.]+", prompt):
        prompt = f"{prompt} --v 7"

    return prompt


def generate_midjourney_prompts_gpt(
    recipe: Recipe,
    focus_keyword: str,
    recipe_text: str,
    settings: Settings,
    logger: logging.Logger,
    seed: Optional[int] = None,
) -> List[Dict]:
    """
    Generate 3 Midjourney image prompts using GPT analysis (legacy approach).

    Returns:
        List of 3 prompt dictionaries (featured, instructions_process, serving)
    """
    if not settings.openai_api_key:
        logger.info("OpenAI API key not set; using template prompts")
        return generate_template_prompts(recipe, focus_keyword, settings)

    seed = seed if seed is not None else generate_random_seed()
    template_payload = generate_template_prompts(recipe, focus_keyword, settings, seed)
    template_json = json.dumps(template_payload, ensure_ascii=True, indent=2)

    if not focus_keyword:
        focus_keyword = recipe.name or "recipe"

    style_anchor = settings.style_anchor or DEFAULT_STYLE_ANCHOR

    article_context = recipe_text[:3000] if recipe_text else ""
    if not article_context:
        article_context = f"""
Recipe: {recipe.name or focus_keyword}
Description: {recipe.description or 'Delicious recipe'}
Ingredients: {', '.join(recipe.ingredients[:10]) if recipe.ingredients else 'Various ingredients'}
Instructions: {', '.join(recipe.instructions[:5]) if recipe.instructions else 'Follow recipe steps'}
"""

    prompt = f"""
You are a professional food photography director and SEO expert specializing in MidJourney prompts.

Analyze this recipe article and generate exactly 3 MidJourney image prompts with comprehensive SEO metadata:

Article Topic: {recipe.name or focus_keyword}
Focus Keyword: {focus_keyword}
Article Content:
{article_context}

Generate prompts for these 3 images in order:
1. Featured Image (Pinterest viral close-up hero) --ar 3:2
2. Instructions-only process photo (Hands preparing the dish) --ar 2:3
3. Serving Image (Pinterest viral plated serving hero) --ar 2:3

STRICT RULES FOR IMAGE GENERATION:
- Featured image MUST match Pinterest viral dessert/recipe hero styling:
  • Tight close-up hero framing of the dish
  • Soft natural kitchen lighting with warm highlights
  • Glossy texture detail, realistic crumbs, sauce drips, layered texture
  • Shallow depth of field, DSLR 85mm aesthetic, rich contrast
  • Clean composition with negative space for text overlay
  • Natural marble or soft neutral surface may be visible
- Instructions process photo MUST show hands actively preparing/cooking the dish
- Serving image MUST match featured style:
  • Tight plated hero shot, commercial food blog look
  • Plate is secondary but visible, natural marble/neutral surface present
  • Warm cozy tones, realistic highlights/crumbs, same lighting family as featured
- Include slight natural imperfections and human-made food styling
- Avoid CGI / synthetic look
- Avoid any pork, bacon, ham, lard, gelatin, or alcohol references.
- Maintain exact continuity using the same style anchor and seed.
- NO text, NO watermark, NO labels, NO writing on the image.
- Professional magazine-quality food photography.

For each image, provide:
- A detailed MidJourney prompt with style anchor and seed
- Exact placement location in the article
- Brief description of what the image shows
- Complete SEO metadata (alt text, filename, caption, description)

SEO Requirements:
- Alt Text: Must include exact keyword "{focus_keyword}"
- Filename: Hyphenated, lowercase, include keyword
- Caption: Short, descriptive, human-readable
- Description: Full sentence describing dish with continuity reference

Use this seed for ALL prompts: {seed}
Include this style anchor in ALL prompts: "{style_anchor}"

Return the response in this exact JSON format:
{template_json}

Output ONLY JSON.
"""

    try:
        payload = {
            "model": settings.model_name,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are a professional food photography director. "
                        "Generate detailed MidJourney prompts with exact placement metadata. "
                        "Output JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_output_tokens": 2000,
        }

        output_text = responses_create_text(settings, payload, logger)

        try:
            if "```json" in output_text:
                json_text = output_text.split("```json")[1].split("```")[0].strip()
            elif "```" in output_text:
                json_text = output_text.split("```")[1].split("```")[0].strip()
            else:
                json_text = _extract_json_from_text(output_text)

            if not json_text:
                raise ValueError("No JSON found in response")

            data = json.loads(json_text)
            images, note = _normalize_gpt_images_payload(data, template_payload)
            if note:
                logger.warning(f"GPT prompt response normalized with fallback: {note}")
            return images

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse GPT prompt response: {e}; using template prompts")
            return template_payload

    except Exception as e:
        logger.warning(f"GPT prompt generation failed: {e}; using template prompts")
        return template_payload


def _extract_json_from_text(text: str) -> str:
    """Extract JSON from text response."""
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    return match.group(1) if match else ""


def _normalize_gpt_images_payload(
    data: object,
    template_payload: List[Dict],
) -> Tuple[List[Dict], str]:
    if not isinstance(template_payload, list) or len(template_payload) != 3:
        return template_payload, "Invalid template payload"

    template_by_type = {item.get("type"): item for item in template_payload}
    ordered_types = ["featured", "instructions_process", "serving"]

    if isinstance(data, dict):
        images = data.get("images") or data.get("data") or data.get("prompts")
    elif isinstance(data, list):
        images = data
    else:
        return template_payload, "Invalid JSON root"

    if not isinstance(images, list) or not images:
        return template_payload, "Invalid images array"

    result_by_type: Dict[str, Dict] = {}
    for idx, item in enumerate(images[:3]):
        if not isinstance(item, dict):
            continue
        raw_type = (item.get("type") or item.get("image_type") or item.get("name") or "").strip().lower()
        image_type = raw_type if raw_type in template_by_type else ordered_types[idx]
        base = dict(template_by_type.get(image_type, template_payload[idx]))
        prompt = item.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            base["prompt"] = sanitize_midjourney_prompt(
                _inject_no_text_exclusions(prompt.strip()),
                image_type,
            )
        if isinstance(item.get("placement"), str):
            base["placement"] = item["placement"]
        if isinstance(item.get("description"), str):
            base["description"] = item["description"]
        if isinstance(item.get("seo_metadata"), dict):
            base["seo_metadata"] = {**base.get("seo_metadata", {}), **item["seo_metadata"]}
        result_by_type[base.get("type", image_type)] = base

    for image_type in ordered_types:
        if image_type not in result_by_type:
            result_by_type[image_type] = template_by_type[image_type]

    return [result_by_type[image_type] for image_type in ordered_types], ""


def generate_template_prompts(
    recipe: Recipe,
    focus_keyword: str,
    settings: Settings,
    seed: Optional[int] = None,
) -> List[Dict]:
    """Generate shared template prompts via the canonical prompt service."""
    if seed is None:
        seed = generate_random_seed()

    dish_name = recipe.name or focus_keyword or "the dish"
    style_anchor = settings.style_anchor or DEFAULT_STYLE_ANCHOR
    return build_template_prompt_payload(
        dish_name=dish_name,
        focus_keyword=focus_keyword,
        style_anchor=style_anchor,
        seed=seed,
    )
    
