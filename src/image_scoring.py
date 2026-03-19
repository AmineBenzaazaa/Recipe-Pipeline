import json
import logging
import re
from typing import List

from .config import Settings
from .openai_client import responses_create_text


def _extract_json_from_text(text: str) -> str:
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    return match.group(1) if match else ""


def _dedupe_urls(urls: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for url in urls:
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        ordered.append(url)
    return ordered


def pick_most_realistic_image(
    image_urls: List[str],
    settings: Settings,
    logger: logging.Logger,
) -> str:
    candidates = _dedupe_urls(image_urls)
    if not candidates:
        return ""
    if not settings.image_realism_scoring:
        return candidates[0]
    if not settings.openai_api_key:
        logger.warning("Realism scoring enabled but OpenAI API key is missing.")
        return candidates[0]
    if len(candidates) < 2:
        return candidates[0]

    # Limit candidates to control cost.
    candidates = candidates[:4]
    instruction = (
        "You are a strict visual judge. Score each image for photorealism "
        "and overall realism (0-10, higher is more realistic). Choose the "
        "single most realistic image. If there is a tie, pick the lowest index. "
        "Return ONLY JSON in this schema: "
        "{\"best_index\": 0, \"scores\": [0,0,0,0], \"notes\": \"optional\"}."
    )
    content = [{"type": "input_text", "text": instruction}]
    for url in candidates:
        content.append({"type": "input_image", "image_url": url})

    payload = {
        "model": settings.vision_model,
        "input": [{"role": "user", "content": content}],
        "max_output_tokens": 300,
    }

    output_text = responses_create_text(settings, payload, logger)
    json_text = _extract_json_from_text(output_text)
    if not json_text:
        logger.warning("Realism scoring returned no JSON; using first candidate.")
        return candidates[0]

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        logger.warning("Realism scoring JSON invalid; using first candidate.")
        return candidates[0]

    best_index = data.get("best_index")
    if isinstance(best_index, str) and best_index.isdigit():
        best_index = int(best_index)
    if isinstance(best_index, int):
        if 0 <= best_index < len(candidates):
            return candidates[best_index]
        # Allow 1-based indexes as a fallback.
        if 1 <= best_index <= len(candidates):
            return candidates[best_index - 1]

    logger.warning("Realism scoring missing best_index; using first candidate.")
    return candidates[0]
