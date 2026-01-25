import base64
import json
import logging
import mimetypes
import re
from typing import List

from .config import Settings
from .formatters import build_image_prompts
from .openai_client import responses_create_text


def _encode_image(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/jpeg"
    with open(path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _extract_json_from_text(text: str) -> str:
    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    return match.group(1) if match else ""


def _validate_prompt_payload(payload: List[dict], focus_keyword: str, style_anchor: str, seed: int) -> bool:
    if not isinstance(payload, list) or len(payload) != 3:
        return False
    for item in payload:
        if not isinstance(item, dict):
            return False
        for key in ["type", "prompt", "placement", "description", "seo_metadata"]:
            if key not in item:
                return False
        seo = item.get("seo_metadata", {})
        if not isinstance(seo, dict):
            return False
        alt_text = seo.get("alt_text", "")
        if focus_keyword not in alt_text:
            return False
        prompt_text = item.get("prompt", "")
        if style_anchor not in prompt_text:
            return False
        if f"--seed {seed}" not in prompt_text:
            return False
    return True


def generate_prompts_from_images(
    image_paths: List[str],
    image_urls: List[str],
    dish_name: str,
    focus_keyword: str,
    style_anchor: str,
    seed: int,
    recipe_context: dict,
    settings: Settings,
    logger: logging.Logger,
) -> List[dict]:
    # Always return template prompts if vision is disabled
    if not settings.use_vision_prompts:
        logger.info("Vision prompts disabled - using template prompts")
        return build_image_prompts(dish_name, focus_keyword, style_anchor, seed)
    
    if not settings.openai_api_key:
        return build_image_prompts(dish_name, focus_keyword, style_anchor, seed)
    if not image_paths and not image_urls:
        return build_image_prompts(dish_name, focus_keyword, style_anchor, seed)

    content = [
        {
            "type": "input_text",
            "text": (
                "Analyze the food photos to confirm the dish and overall photostyle cues. "
                "Use the recipe context for accurate, specific visual details (texture, frosting, "
                "garnish, color, plating, props). Generate professional food photography prompts "
                "suitable for recipe blog articles. IMPORTANT RULES: "
                "1. NO text overlay, NO watermark, NO labels, NO writing on the image "
                "2. Professional magazine-quality food photography "
                "3. Clean composition, appetizing presentation "
                "4. High resolution, sharp focus, professional lighting "
                "5. Restaurant-quality styling, commercial food photography "
                "Then output a JSON array with exactly 3 objects that match the schema and text "
                "templates provided. Use the dish name and focus keyword exactly as given. "
                "Fill [dish name] with the dish name, and fill {style_anchor} and {seed} with "
                "the provided values. Keep the template structure but add a short descriptive "
                "clause right after the dish name in each prompt to make it specific to this recipe. "
                "Include the professional photography rules in each prompt. Output ONLY JSON."
            ),
        }
    ]

    if recipe_context:
        content.append(
            {
                "type": "input_text",
                "text": f"Recipe context: {json.dumps(recipe_context, ensure_ascii=True)}",
            }
        )

    image_inputs = []
    for path in image_paths[:2]:
        image_inputs.append({"type": "input_image", "image_url": _encode_image(path)})
    if not image_inputs:
        for url in image_urls[:2]:
            image_inputs.append({"type": "input_image", "image_url": url})

    content.extend(image_inputs)

    template_payload = build_image_prompts(dish_name, focus_keyword, style_anchor, seed)
    template_json = json.dumps(template_payload, ensure_ascii=True, indent=2)

    payload = {
        "model": settings.vision_model,
        "input": [
            {"role": "system", "content": "You are a careful JSON-only assistant."},
            {
                "role": "user",
                "content": content
                + [
                    {
                        "type": "input_text",
                        "text": (
                            "Use this schema and structure exactly as reference:"
                            f"\n{template_json}"
                        ),
                    }
                ],
            },
        ],
        "max_output_tokens": 1200,
    }

    output_text = responses_create_text(settings, payload, logger)
    json_text = _extract_json_from_text(output_text)
    if not json_text:
        logger.warning("Vision response did not include JSON; using template prompts")
        return template_payload

    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        logger.warning("Vision response JSON invalid; using template prompts")
        return template_payload

    if not _validate_prompt_payload(payload, focus_keyword, style_anchor, seed):
        logger.warning("Vision prompts failed validation; using template prompts")
        return template_payload

    return payload
