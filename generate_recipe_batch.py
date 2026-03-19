import argparse
import csv
import io
import logging
import os
import sys
import tempfile
import time
import json
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import requests
from PIL import Image

from src.config import load_settings
from src.csv_writer import append_row, load_template_headers
from src.enrich_recipe import enrich_recipe_metadata
from src.extract_images import (
    download_images,
    extract_image_urls,
    extract_primary_image_url,
)
from src.extract_recipe import extract_recipe_from_html, fetch_html
from src.faq_provider import get_faqs
from src.formatters import (
    build_prompt_dish_name,
    format_faq_text,
    format_recipe_text,
    seed_from_string,
)
from src.halal import make_recipe_halal, sanitize_text_halal
from src.image_generator import generate_prompt_images
from src.imagineapi_client import generate_imagineapi_images
from src.midjourney_prompt_sanitizer import sanitize_midjourney_prompt
from src.openai_vision import generate_prompts_from_images
from src.midjourney_prompts import generate_midjourney_prompts_gpt, generate_template_prompts
from src.model_routing import evaluate_row_quality, resolve_model_fallback_config
from src.output_language import localize_output_row, resolve_output_language
from src.openai_client import responses_create_text
from src.models import Recipe
from src.midjourney_client import (
    MidjourneyQueueRunner,
    generate_midjourney_images,
    generate_midjourney_images_queue,
)
from src.sheets_client import GoogleSheetWriter

DEFAULT_HEADERS = [
    "focus_keyword",
    "topic",
    "faq_text",
    "recipe_text",
    "model_name",
    "temperature",
    "target_words",
    "use_multi_call",
    "featured_image_prompt",
    "instructions_process_image_prompt",
    "serving_image_prompt",
    "WPRM_recipecard_image_prompt",
    "featured_image_generated_url",
    "instructions_process_image_generated_url",
    "serving_image_generated_url",
    "WPRM_recipe)card_url",
]

BLOCKED_DOMAINS = {
    "etsy.com",
    "gumroad.com",
}
RETRYABLE_STATUSES = {"no_html", "missing_prompts", "error"}
PET_KEYWORD_HINTS = ("dog", "dogs", "puppy", "puppies", "pup", "canine", "pet")


def _lock_recipe_title_to_focus_keyword(recipe, focus_keyword: str):
    if not focus_keyword:
        return recipe
    return recipe.model_copy(update={"name": focus_keyword})


def _apply_image_aliases(row: dict) -> None:
    """Add compatibility aliases for image URL columns used by older templates."""
    alias_map = {
        "featured_image_url": "featured_image_generated_url",
        "instructions_process_image_url": "instructions_process_image_generated_url",
        "serving_image_url": "serving_image_generated_url",
        "WPRM_recipecard_url": "WPRM_recipe)card_url",
    }
    for alias, source in alias_map.items():
        if alias not in row and source in row:
            row[alias] = row.get(source, "") or ""


def _fetch_image_size(url: str, timeout: float) -> Optional[tuple[int, int]]:
    if not url or not url.startswith("http"):
        return None
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        with Image.open(io.BytesIO(response.content)) as img:
            return img.width, img.height
    except Exception:
        return None


def _normalize_midjourney_urls(
    generated_urls: dict, timeout_seconds: float, logger: logging.Logger
) -> None:
    featured_url = generated_urls.get("featured", "")
    serving_url = generated_urls.get("serving", "")
    if not featured_url or not serving_url:
        return
    featured_size = _fetch_image_size(featured_url, timeout_seconds)
    serving_size = _fetch_image_size(serving_url, timeout_seconds)
    if not featured_size or not serving_size:
        return
    featured_landscape = featured_size[0] >= featured_size[1]
    serving_landscape = serving_size[0] >= serving_size[1]
    if featured_landscape and not serving_landscape:
        return
    if serving_landscape and not featured_landscape:
        logger.info("Swapping featured/serving URLs based on aspect ratio validation.")
        generated_urls["featured"] = serving_url
        generated_urls["serving"] = featured_url


def _sanitize_prompt_text(prompt: str) -> str:
    if not prompt:
        return prompt
    cleaned = " ".join(prompt.split())
    if not cleaned:
        return cleaned
    if cleaned.lower().startswith("prompt:"):
        cleaned = cleaned[7:].lstrip()
    while cleaned and cleaned[0] in "-*,":
        cleaned = cleaned[1:].lstrip()
    if cleaned and cleaned[0].isdigit():
        parts = cleaned.split(maxsplit=1)
        if len(parts) == 2 and parts[0].rstrip(".").isdigit():
            cleaned = parts[1].strip()
    return cleaned


def _prefix_prompt_with_image_url(prompt: str, image_url: str) -> str:
    if not prompt or not image_url:
        return prompt
    cleaned_prompt = prompt.strip()
    cleaned_url = image_url.strip()
    if not cleaned_url:
        return prompt
    parsed_url = urlparse(cleaned_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        return prompt
    if cleaned_prompt.startswith("http://") or cleaned_prompt.startswith("https://"):
        return prompt
    return f"{cleaned_url} {cleaned_prompt}"


def _wait_if_paused(logger: logging.Logger) -> None:
    pause_file = os.getenv("PIPELINE_PAUSE_FILE", "").strip()
    if not pause_file:
        return
    while os.path.exists(pause_file):
        logger.info("Paused. Remove %s to resume processing.", pause_file)
        time.sleep(5)


def _setup_logger(level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger("recipe_batch")


def _validate_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_blocked_domain(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    if not netloc:
        return False
    return any(netloc == domain or netloc.endswith(f".{domain}") for domain in BLOCKED_DOMAINS)


def _validated_prompt_image_url(
    image_url: str,
    timeout_seconds: float,
    logger: logging.Logger,
) -> str:
    cleaned_url = (image_url or "").strip()
    if not cleaned_url:
        return ""

    if not _validate_url(cleaned_url):
        logger.warning(
            "Primary image URL is invalid; skipping prompt URL prefix: %s",
            cleaned_url,
        )
        return ""

    if not _fetch_image_size(cleaned_url, timeout_seconds):
        logger.warning(
            "Primary image URL is unreachable or not a valid image; skipping prompt URL prefix: %s",
            cleaned_url,
        )
        return ""

    return cleaned_url


def _extract_json_object(text: str) -> str:
    if not text:
        return ""
    cleaned = text.strip()
    if not cleaned:
        return ""
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    return match.group(0) if match else ""


def _default_keyword_only_recipe(focus_keyword: str) -> Recipe:
    pet_mode = any(token in focus_keyword.lower() for token in PET_KEYWORD_HINTS)
    if pet_mode:
        return Recipe(
            name=focus_keyword,
            description=f"A simple homemade {focus_keyword.lower()} recipe for dogs.",
            servings="4 servings",
            prep_time="15 min",
            cook_time="25 min",
            total_time="40 min",
            calories="250 calories",
            cuisine="Pet Food",
            course="Dog Food",
            ingredients=[
                "2 cups dog-safe protein source",
                "1 cup dog-safe carbohydrate source",
                "1/2 cup dog-safe vegetables",
                "2 cups water or unsalted broth",
                "1 tablespoon dog-safe oil",
            ],
            instructions=[
                "Prepare and portion the ingredients into bite-size pieces.",
                "Cook the protein thoroughly in a pan or pot over medium heat.",
                "Add carbohydrates, vegetables, and liquid, then simmer until tender.",
                "Stir in the oil and cook briefly until the mixture is evenly combined.",
                "Cool completely before serving to your dog in appropriate portions.",
            ],
            notes="Use only dog-safe ingredients and consult your veterinarian for diet changes.",
            extraction_method="keyword_only_default",
        )

    return Recipe(
        name=focus_keyword,
        description=f"A homemade {focus_keyword.lower()} recipe with clear ingredients and steps.",
        servings="4 servings",
        prep_time="15 min",
        cook_time="20 min",
        total_time="35 min",
        calories="300 calories",
        cuisine="American",
        course="Main Course",
        ingredients=[
            "2 cups main ingredient",
            "1 cup supporting ingredient",
            "1/2 cup aromatics",
            "2 tablespoons fat or oil",
            "salt and pepper to taste",
        ],
        instructions=[
            "Prep and measure all ingredients.",
            "Cook the base ingredients over medium heat until aromatic.",
            "Add remaining ingredients and cook until properly tender.",
            "Adjust seasoning and texture as needed.",
            "Serve warm with your preferred garnish.",
        ],
        extraction_method="keyword_only_default",
    )


def _generate_recipe_from_keyword(
    focus_keyword: str,
    settings,
    logger: logging.Logger,
) -> Recipe:
    fallback = _default_keyword_only_recipe(focus_keyword)
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set; using keyword-only default recipe for '%s'", focus_keyword)
        return fallback

    pet_mode = any(token in focus_keyword.lower() for token in PET_KEYWORD_HINTS)
    guardrails = (
        "This is for dogs. Use only dog-safe ingredients. Never include onion, garlic, chocolate, raisins, grapes, xylitol, alcohol."
        if pet_mode
        else "Keep ingredients practical and common for home cooking."
    )
    prompt = (
        "Create one complete recipe from a focus keyword. Return JSON only.\n"
        "Required keys: name, description, servings, prep_time, cook_time, total_time, calories, cuisine, course, ingredients, instructions, notes.\n"
        "Rules:\n"
        "- name must stay very close to the focus keyword.\n"
        "- ingredients must be 5-12 concise strings.\n"
        "- instructions must be 5-10 clear steps.\n"
        "- Keep output realistic and publication-ready.\n"
        f"- {guardrails}\n"
        f"Focus keyword: {focus_keyword}"
    )
    payload = {
        "model": settings.model_name,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "temperature": 0.2,
        "max_output_tokens": 2000,
    }
    output_text = responses_create_text(settings, payload, logger)
    json_text = _extract_json_object(output_text)
    if not json_text:
        logger.warning("Keyword-only generation returned no JSON for '%s'; using fallback.", focus_keyword)
        return fallback

    try:
        parsed = json.loads(json_text)
    except Exception:
        logger.warning("Keyword-only generation returned invalid JSON for '%s'; using fallback.", focus_keyword)
        return fallback

    if not isinstance(parsed, dict):
        return fallback

    ingredients = parsed.get("ingredients")
    if not isinstance(ingredients, list):
        ingredients = fallback.ingredients
    else:
        ingredients = [str(item).strip() for item in ingredients if str(item).strip()]
    instructions = parsed.get("instructions")
    if not isinstance(instructions, list):
        instructions = fallback.instructions
    else:
        instructions = [str(item).strip() for item in instructions if str(item).strip()]

    return Recipe(
        name=str(parsed.get("name") or focus_keyword).strip() or focus_keyword,
        description=str(parsed.get("description") or fallback.description or "").strip(),
        servings=str(parsed.get("servings") or fallback.servings or "").strip(),
        prep_time=str(parsed.get("prep_time") or fallback.prep_time or "").strip(),
        cook_time=str(parsed.get("cook_time") or fallback.cook_time or "").strip(),
        total_time=str(parsed.get("total_time") or fallback.total_time or "").strip(),
        calories=str(parsed.get("calories") or fallback.calories or "").strip(),
        cuisine=str(parsed.get("cuisine") or fallback.cuisine or "").strip(),
        course=str(parsed.get("course") or fallback.course or "").strip(),
        ingredients=ingredients or fallback.ingredients,
        instructions=instructions or fallback.instructions,
        notes=str(parsed.get("notes") or fallback.notes or "").strip(),
        extraction_method="keyword_only_ai",
    )


def _load_input_csv(path: str, allow_missing_url: bool = False) -> List[Tuple[str, str, str]]:
    """
    Load recipe targets from CSV file.
    
    Supports multiple formats:
    1. focus_keyword, url (original format)
    2. Recipe Name, Pinterest URL, Recipe URL (new format)
    3. Recipe Name with missing Recipe URL when allow_missing_url=True
    
    Args:
        path: Path to CSV file
    
    Returns:
        List of (focus_keyword, recipe_url, pinterest_url) tuples
    """
    import logging
    logger = logging.getLogger(__name__)
    
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames
        logger.info(f"CSV Headers found: {headers}")
        
        for idx, row in enumerate(reader):
            # Try original format first
            keyword = (row.get("focus_keyword") or "").strip()
            url = (row.get("url") or "").strip()
            pinterest_url = ""
            
            # If not found, try new format: Recipe Name, Pinterest URL, Recipe URL
            if not keyword or not url:
                recipe_name = (row.get("Recipe Name") or row.get("recipe_name") or "").strip()
                recipe_url = (row.get("Recipe URL") or row.get("recipe_url") or "").strip()
                pinterest_url = (row.get("Pinterest URL") or row.get("pinterest_url") or "").strip()
                
                if recipe_name:
                    keyword = recipe_name
                if recipe_url:
                    url = recipe_url
                else:
                    if allow_missing_url:
                        logger.info(
                            "Row %s: Recipe Name='%s', Recipe URL missing (keyword-only mode enabled)",
                            idx + 1,
                            recipe_name,
                        )
                    else:
                        logger.warning(
                            "Row %s: Recipe Name='%s', Recipe URL missing (skipping)",
                            idx + 1,
                            recipe_name,
                        )
            
            if keyword and (url or allow_missing_url):
                rows.append((keyword, url, pinterest_url))
                logger.debug(f"Row {idx+1}: Added '{keyword}' -> '{url}'")
            else:
                logger.warning(f"Row {idx+1}: Skipped (keyword='{keyword}', url='{url}')")
    
    logger.info(f"Loaded {len(rows)} valid recipe targets from CSV")
    return rows


def _resolve_pinterest_visit_url(
    pinterest_url: str,
    timeout: float,
    logger: logging.Logger,
) -> str:
    if not pinterest_url:
        return ""
    try:
        import pin_extract
    except Exception as exc:
        logger.warning("Unable to import pin_extract for fallback: %s", exc)
        return ""

    pin_id = pin_extract.extract_pin_id(pinterest_url)
    if not pin_id:
        logger.warning("Invalid Pinterest URL for fallback: %s", pinterest_url)
        return ""

    visit_url = ""
    api_data = pin_extract.fetch_pin_api(pin_id, timeout)
    if api_data:
        _title, visit_url = pin_extract.extract_fields_from_dict(api_data)

    if not visit_url:
        resource_data = pin_extract.fetch_pin_resource(pin_id, timeout)
        if resource_data:
            _title, visit_url = pin_extract.extract_fields_from_dict(resource_data)

    if not visit_url:
        try:
            status, html_text = pin_extract.fetch_url(pinterest_url, timeout)
        except Exception as exc:
            logger.warning("Pinterest HTML fetch failed: %s", exc)
            html_text = ""
        if html_text:
            _title, html_visit, _context = pin_extract.extract_from_html(
                html_text, pin_id, pinterest_url
            )
            if html_visit:
                visit_url = html_visit

    if visit_url and not pin_extract.is_candidate_external_url(visit_url):
        return ""

    return visit_url or ""


def _process_recipe(
    focus_keyword: str,
    url: str,
    pinterest_url: str,
    output_language: str,
    settings,
    logger: logging.Logger,
    mj_runner: Optional[MidjourneyQueueRunner] = None,
) -> Tuple[dict, str]:
    html = ""
    if (url or "").strip():
        if (not _validate_url(url) or _is_blocked_domain(url)) and pinterest_url:
            fallback_url = _resolve_pinterest_visit_url(
                pinterest_url, settings.request_timeout, logger
            )
            if fallback_url and fallback_url != url:
                logger.info("Using Pinterest visit site URL: %s", fallback_url)
                url = fallback_url

        if not _validate_url(url):
            logger.warning("Invalid URL skipped: %s", url)
            return {}, "invalid_url"
        if _is_blocked_domain(url):
            logger.warning("Blocked domain skipped: %s", url)
            return {}, "blocked_domain"

        html = fetch_html(url, settings, logger)
        if not html and pinterest_url:
            fallback_url = _resolve_pinterest_visit_url(
                pinterest_url, settings.request_timeout, logger
            )
            if fallback_url and fallback_url != url:
                logger.info(
                    "Retrying with Pinterest visit site URL: %s", fallback_url
                )
                url = fallback_url
                html = fetch_html(url, settings, logger)
        if not html:
            logger.warning("No HTML for %s", url)
            return {}, "no_html"
        recipe = extract_recipe_from_html(html, url, settings, logger)
    else:
        logger.info("Keyword-only generation mode for '%s' (no source URL).", focus_keyword)
        recipe = _generate_recipe_from_keyword(focus_keyword, settings, logger)

    recipe = enrich_recipe_metadata(recipe, html, focus_keyword, settings, logger)
    recipe = make_recipe_halal(recipe)
    sanitized_keyword = sanitize_text_halal(focus_keyword)
    if sanitized_keyword:
        focus_keyword = sanitized_keyword
    output_recipe = _lock_recipe_title_to_focus_keyword(recipe, focus_keyword)

    # Only download images if we're using vision prompts (expensive)
    primary_image_url = extract_primary_image_url(
        html, base_url=url, recipe_image_urls=recipe.image_urls
    )
    image_urls = []
    downloaded = []
    if settings.use_vision_prompts:
        image_urls = extract_image_urls(html, base_url=url, recipe_image_urls=recipe.image_urls)
        with tempfile.TemporaryDirectory() as temp_dir:
            downloaded = download_images(
                image_urls, temp_dir, settings, logger, limit=3, referer=url
            )
    
    # Generate prompts using GPT (legacy approach) or fallback to templates
    recipe_text_formatted = format_recipe_text(output_recipe)
    seed = seed_from_string(url or focus_keyword)

    # Try GPT-based prompt generation first (like legacy.py) - this is the preferred method
    if settings.openai_api_key and not settings.use_vision_prompts:
        logger.info("Using GPT-based Midjourney prompt generation (legacy approach)")
        prompts = generate_midjourney_prompts_gpt(
            recipe,
            focus_keyword,
            recipe_text_formatted,
            settings,
            logger,
        )
    else:
        # Fallback to template-based or vision-based prompts
        recipe_context = {
            "name": recipe.name,
            "description": recipe.description,
            "ingredients": recipe.ingredients[:12],
            "instructions": recipe.instructions[:5],
            "servings": recipe.servings,
        }
        dish_prompt_name = build_prompt_dish_name(recipe, focus_keyword)
        
        if settings.use_vision_prompts and (downloaded or image_urls):
            prompts = generate_prompts_from_images(
                downloaded,
                image_urls,
                dish_prompt_name,
                focus_keyword,
                settings.style_anchor,
                seed,
                recipe_context,
                settings,
                logger,
            )
        else:
            # Use template prompts (legacy-style simple prompts)
            prompts = generate_template_prompts(recipe, focus_keyword, settings, seed)

    faq_items = get_faqs(focus_keyword, recipe, settings, logger)

    prompt_map = {item.get("type"): item for item in prompts if isinstance(item, dict)}
    featured_prompt = _sanitize_prompt_text(prompt_map.get("featured", {}).get("prompt", ""))
    instructions_prompt = _sanitize_prompt_text(
        prompt_map.get("instructions_process", {}).get("prompt", "")
    )
    serving_prompt = _sanitize_prompt_text(prompt_map.get("serving", {}).get("prompt", ""))
    wprm_prompt = _sanitize_prompt_text(
        prompt_map.get("wprm_recipecard", {}).get("prompt", "")
        or prompt_map.get("recipecard", {}).get("prompt", "")
        or prompt_map.get("recipe_card", {}).get("prompt", "")
    )
    missing_prompt_types = [
        prompt_type
        for prompt_type, prompt in (
            ("featured", featured_prompt),
            ("instructions_process", instructions_prompt),
            ("serving", serving_prompt),
        )
        if not prompt
    ]
    status = "ok"
    if missing_prompt_types:
        logger.warning(
            "Missing prompt types %s for %s; falling back to template prompts",
            ", ".join(missing_prompt_types),
            url,
        )
        prompts = generate_template_prompts(recipe, focus_keyword, settings, seed)
        prompt_map = {item.get("type"): item for item in prompts if isinstance(item, dict)}
        featured_prompt = prompt_map.get("featured", {}).get("prompt", "")
        instructions_prompt = prompt_map.get("instructions_process", {}).get("prompt", "")
        serving_prompt = prompt_map.get("serving", {}).get("prompt", "")
        missing_prompt_types = [
            prompt_type
            for prompt_type, prompt in (
                ("featured", featured_prompt),
                ("instructions_process", instructions_prompt),
                ("serving", serving_prompt),
            )
            if not prompt
        ]
        status = "missing_prompts" if missing_prompt_types else "ok"

    if not wprm_prompt:
        wprm_prompt = featured_prompt

    validated_prompt_image_url = _validated_prompt_image_url(
        primary_image_url,
        settings.request_timeout,
        logger,
    )
    if validated_prompt_image_url:
        featured_prompt = _prefix_prompt_with_image_url(
            featured_prompt, validated_prompt_image_url
        )
        serving_prompt = _prefix_prompt_with_image_url(
            serving_prompt, validated_prompt_image_url
        )
        wprm_prompt = _prefix_prompt_with_image_url(wprm_prompt, validated_prompt_image_url)

    featured_prompt = sanitize_midjourney_prompt(featured_prompt, "featured")
    instructions_prompt = sanitize_midjourney_prompt(
        instructions_prompt, "instructions_process"
    )
    serving_prompt = sanitize_midjourney_prompt(serving_prompt, "serving")
    wprm_prompt = sanitize_midjourney_prompt(wprm_prompt, "wprm_recipecard")
    
    # Generate images only if enabled in settings
    if settings.generate_images:
        prompt_text_map = {
            "featured": featured_prompt,
            "instructions_process": instructions_prompt,
            "serving": serving_prompt,
            "wprm_recipecard": wprm_prompt,
        }
        if settings.image_engine == "midjourney":
            if mj_runner is not None:
                generated_urls = generate_midjourney_images_queue(
                    prompt_text_map, mj_runner, logger
                )
            else:
                generated_urls = generate_midjourney_images(
                    prompt_text_map, settings, logger
                )
            _normalize_midjourney_urls(
                generated_urls, settings.request_timeout, logger
            )
        elif settings.image_engine == "imagineapi":
            generated_urls = generate_imagineapi_images(
                prompt_text_map, settings, logger
            )
        else:
            generated_urls = generate_prompt_images(
                prompt_text_map, focus_keyword, settings, logger
            )
    else:
        logger.info("Image generation disabled - prompts generated but images not created")
        generated_urls = {
            "featured": "",
            "instructions_process": "",
            "serving": "",
        }

    row = {
        "focus_keyword": focus_keyword,
        "topic": focus_keyword,
        "faq_text": format_faq_text(faq_items),
        "recipe_text": recipe_text_formatted,
        "model_name": settings.model_name,
        "temperature": settings.temperature,
        "target_words": settings.target_words,
        "use_multi_call": str(settings.use_multi_call),
        "featured_image_prompt": featured_prompt,
        "instructions_process_image_prompt": instructions_prompt,
        "serving_image_prompt": serving_prompt,
        "WPRM_recipecard_image_prompt": wprm_prompt,
        "featured_image_generated_url": generated_urls.get("featured", ""),
        "instructions_process_image_generated_url": generated_urls.get(
            "instructions_process", ""
        ),
        "serving_image_generated_url": generated_urls.get("serving", ""),
        "WPRM_recipe)card_url": generated_urls.get("wprm_recipecard", "")
        or generated_urls.get("featured", ""),
    }

    _apply_image_aliases(row)
    row = localize_output_row(row, output_language, settings, logger)
    return row, status


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate recipe batch CSV rows")
    parser.add_argument("--keyword", help="Focus keyword")
    parser.add_argument("--url", action="append", help="Recipe URL (repeatable)")
    parser.add_argument(
        "--allow-missing-url",
        action="store_true",
        help="Allow rows without source URL and generate recipes directly from keywords.",
    )
    parser.add_argument("--input", help="Input CSV with focus_keyword,url columns")
    parser.add_argument("--out", required=True, help="Output CSV path")
    parser.add_argument("--template", help="Template CSV path (optional)")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--sheet-url", help="Google Sheet URL (optional)")
    parser.add_argument("--sheet-tab", help="Google Sheet worksheet/tab name (optional)")
    parser.add_argument(
        "--output-language",
        help=(
            "Optional output language code override (for example: en, pl). "
            "If omitted, language is resolved from sheet tab mapping."
        ),
    )
    parser.add_argument(
        "--sheet-credentials",
        help="Path to Google service account JSON (optional)",
    )
    parser.add_argument(
        "--sheet-ready-value",
        help="Optional value to populate the Ready column (optional)",
        default=None,
    )

    args = parser.parse_args()

    logger = _setup_logger(args.log_level)
    settings = load_settings()
    fallback_config = resolve_model_fallback_config(current_model_name=settings.model_name)
    primary_settings = (
        settings.model_copy(update={"model_name": fallback_config.primary_model})
        if fallback_config.primary_model and fallback_config.primary_model != settings.model_name
        else settings
    )
    fallback_settings = (
        settings.model_copy(update={"model_name": fallback_config.fallback_model})
        if fallback_config.enabled and fallback_config.fallback_model
        else settings
    )

    if args.template:
        if not os.path.exists(args.template):
            logger.error("Template CSV not found: %s", args.template)
            return 1
        headers = load_template_headers(args.template)
    else:
        headers = DEFAULT_HEADERS

    sheet_url = args.sheet_url or os.getenv("GOOGLE_SHEET_URL", "")
    sheet_tab = args.sheet_tab or os.getenv("GOOGLE_SHEET_TAB", "")
    output_language = resolve_output_language(
        sheet_tab=sheet_tab,
        explicit_language=args.output_language or os.getenv("OUTPUT_LANGUAGE", ""),
        site_language_map_raw=os.getenv("SITE_LANGUAGE_MAP", ""),
        site_language_map_file=os.getenv("SITE_LANGUAGE_MAP_FILE", ""),
        default_language=os.getenv("DEFAULT_OUTPUT_LANGUAGE", "en"),
    )
    logger.info(
        "Resolved output language: '%s' (sheet_tab='%s')",
        output_language,
        sheet_tab or "",
    )
    logger.info(
        "Model routing: primary='%s' fallback='%s' enabled=%s quality_gate(recipe_chars>=%s,faq_count>=%s)",
        primary_settings.model_name,
        fallback_config.fallback_model or "",
        "yes" if fallback_config.enabled else "no",
        fallback_config.min_recipe_chars,
        fallback_config.min_faq_count,
    )
    sheet_credentials = args.sheet_credentials or os.getenv("GOOGLE_SHEET_CREDENTIALS", "")
    if args.sheet_ready_value is not None:
        sheet_ready_value = args.sheet_ready_value
    elif "GOOGLE_SHEET_READY_VALUE" in os.environ:
        sheet_ready_value = os.getenv("GOOGLE_SHEET_READY_VALUE", "")
    else:
        sheet_ready_value = "ready"
    sheet_writer = None
    if sheet_url:
        if not sheet_credentials:
            logger.error("Google Sheet credentials path is required when --sheet-url is set")
            return 1
        try:
            sheet_writer = GoogleSheetWriter(
                sheet_url=sheet_url,
                worksheet_title=sheet_tab or None,
                credentials_path=sheet_credentials,
                logger=logger,
                expected_headers=headers,
                ready_value=sheet_ready_value,
            )
            logger.info("Google Sheets sync enabled: %s", sheet_url)
        except Exception as exc:
            logger.error("Failed to initialize Google Sheets sync: %s", exc)
            return 1

    targets: List[Tuple[str, str, str]] = []
    if args.input:
        targets.extend(_load_input_csv(args.input, allow_missing_url=bool(args.allow_missing_url)))
    elif args.keyword and args.url:
        targets.extend([(args.keyword, item, "") for item in args.url])
    elif args.keyword and args.allow_missing_url:
        targets.extend([(args.keyword, "", "")])
    else:
        logger.error("Provide --input or both --keyword and --url (or use --allow-missing-url)")
        return 1

    if not targets:
        logger.error("No valid targets found")
        return 1

    mj_runner = None
    if settings.generate_images and settings.image_engine == "midjourney" and settings.midjourney_queue_mode:
        try:
            mj_runner = MidjourneyQueueRunner(settings, logger)
            logger.info("Midjourney queue mode enabled (single browser for batch).")
        except Exception as exc:
            logger.error("Failed to start Midjourney queue runner: %s", exc)
            return 1

    counts = {
        "targets": len(targets),
        "written": 0,
        "invalid_url": 0,
        "no_html": 0,
        "blocked_domain": 0,
        "missing_prompts": 0,
        "skipped": 0,
        "errors": 0,
        "sheet_errors": 0,
    }

    try:
        for focus_keyword, url, pinterest_url in targets:
            attempt = 0
            row = {}
            status = "skipped"
            max_attempts = max(1, settings.max_retries)
            while attempt < max_attempts:
                _wait_if_paused(logger)
                attempt += 1
                if attempt == 1:
                    logger.info("Processing %s", url)
                else:
                    logger.info("Retry attempt %s/%s for %s", attempt, max_attempts, url)
                try:
                    row, status = _process_recipe(
                        focus_keyword,
                        url,
                        pinterest_url,
                        output_language,
                        primary_settings,
                        logger,
                        mj_runner=mj_runner,
                    )
                except Exception as exc:
                    logger.warning("Processing failed for %s: %s", url, exc)
                    row = {}
                    status = "error"
                if status in {"invalid_url", "blocked_domain"}:
                    break
                if status == "ok":
                    break
                if attempt < max_attempts and status in RETRYABLE_STATUSES:
                    logger.info("Retrying %s after status=%s", url, status)
                    time.sleep(settings.sleep_seconds)
                    continue
                break

            if fallback_config.enabled:
                should_try_fallback = status in {"missing_prompts", "error"}
                fallback_reasons = []
                if status == "ok" and row:
                    quality_ok, quality_reasons = evaluate_row_quality(
                        row,
                        fallback_config.min_recipe_chars,
                        fallback_config.min_faq_count,
                    )
                    if not quality_ok:
                        should_try_fallback = True
                        fallback_reasons = quality_reasons

                if should_try_fallback and settings.generate_images:
                    logger.info(
                        "Skipping model fallback for %s because image generation is enabled.",
                        url,
                    )
                    should_try_fallback = False

                if should_try_fallback:
                    reason_text = ", ".join(fallback_reasons) if fallback_reasons else status
                    logger.info(
                        "Trying fallback model '%s' for %s (reason: %s)",
                        fallback_settings.model_name,
                        url,
                        reason_text,
                    )
                    try:
                        fallback_row, fallback_status = _process_recipe(
                            focus_keyword,
                            url,
                            pinterest_url,
                            output_language,
                            fallback_settings,
                            logger,
                            mj_runner=mj_runner,
                        )
                        if fallback_row and fallback_status == "ok":
                            logger.info("Fallback model succeeded for %s", url)
                            row, status = fallback_row, fallback_status
                        else:
                            logger.warning(
                                "Fallback model did not return ok for %s (status=%s); keeping primary output.",
                                url,
                                fallback_status,
                            )
                    except Exception as exc:
                        logger.warning(
                            "Fallback model run failed for %s: %s; keeping primary output.",
                            url,
                            exc,
                        )

            if row:
                ready_header = next(
                    (header for header in headers if header.strip().lower() == "ready"),
                    None,
                )
                if ready_header is not None:
                    row[ready_header] = sheet_ready_value
                append_row(args.out, headers, row)
                counts["written"] += 1
                if sheet_writer:
                    try:
                        sheet_writer.append_row(row)
                    except Exception as exc:
                        counts["sheet_errors"] += 1
                        logger.warning("Failed to append row to Google Sheet: %s", exc)
            else:
                counts["skipped"] += 1
            if status == "error":
                counts["errors"] += 1
            elif status in counts:
                counts[status] += 1
            time.sleep(settings.sleep_seconds)
    finally:
        if mj_runner is not None:
            mj_runner.close()

    logger.info(
        "Done. Output written to %s. Targets=%s Written=%s Skipped=%s InvalidURL=%s NoHTML=%s BlockedDomain=%s MissingPrompts=%s Errors=%s SheetErrors=%s",
        args.out,
        counts["targets"],
        counts["written"],
        counts["skipped"],
        counts["invalid_url"],
        counts["no_html"],
        counts["blocked_domain"],
        counts["missing_prompts"],
        counts["errors"],
        counts["sheet_errors"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
