import argparse
import csv
import logging
import os
import sys
import tempfile
import time
from typing import List, Tuple
from urllib.parse import urlparse

from src.config import load_settings
from src.csv_writer import append_row, load_template_headers
from src.enrich_recipe import enrich_recipe_metadata
from src.extract_images import download_images, extract_image_urls
from src.extract_recipe import extract_recipe_from_html, fetch_html
from src.faq_provider import get_faqs
from src.formatters import (
    build_prompt_dish_name,
    format_faq_text,
    format_recipe_text,
    seed_from_string,
)
from src.image_generator import generate_prompt_images
from src.openai_vision import generate_prompts_from_images
from src.midjourney_prompts import generate_midjourney_prompts_gpt, generate_template_prompts
from src.midjourney_prompts import generate_midjourney_prompts_gpt

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


def _setup_logger(level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger("recipe_batch")


def _validate_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _load_input_csv(path: str) -> List[Tuple[str, str]]:
    """
    Load recipe targets from CSV file.
    
    Supports multiple formats:
    1. focus_keyword, url (original format)
    2. Recipe Name, Pinterest URL, Recipe URL (new format)
    
    Args:
        path: Path to CSV file
    
    Returns:
        List of (focus_keyword, recipe_url) tuples
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
                    logger.warning(f"Row {idx+1}: Recipe Name='{recipe_name}', Recipe URL='{recipe_url}' (missing URL, skipping)")
            
            if keyword and url:
                rows.append((keyword, url))
                logger.debug(f"Row {idx+1}: Added '{keyword}' -> '{url}'")
            else:
                logger.warning(f"Row {idx+1}: Skipped (keyword='{keyword}', url='{url}')")
    
    logger.info(f"Loaded {len(rows)} valid recipe targets from CSV")
    return rows


def _process_recipe(
    focus_keyword: str,
    url: str,
    settings,
    logger: logging.Logger,
) -> dict:
    if not _validate_url(url):
        logger.warning("Invalid URL skipped: %s", url)
        return {}

    html = fetch_html(url, settings, logger)
    if not html:
        logger.warning("No HTML for %s", url)
        return {}

    recipe = extract_recipe_from_html(html, url, settings, logger)
    recipe = enrich_recipe_metadata(recipe, html, focus_keyword, settings, logger)

    # Only download images if we're using vision prompts (expensive)
    image_urls = []
    downloaded = []
    if settings.use_vision_prompts:
        image_urls = extract_image_urls(html, base_url=url, recipe_image_urls=recipe.image_urls)
        with tempfile.TemporaryDirectory() as temp_dir:
            downloaded = download_images(
                image_urls, temp_dir, settings, logger, limit=3, referer=url
            )
    
    # Generate prompts using GPT (legacy approach) or fallback to templates
    recipe_text_formatted = format_recipe_text(recipe)
    
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
        seed = seed_from_string(url or focus_keyword)
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
            prompts = generate_template_prompts(recipe, focus_keyword, settings)

    faq_items = get_faqs(focus_keyword, recipe, settings, logger)

    prompt_map = {item.get("type"): item for item in prompts if isinstance(item, dict)}
    featured_prompt = prompt_map.get("featured", {}).get("prompt", "")
    instructions_prompt = prompt_map.get("instructions_process", {}).get("prompt", "")
    serving_prompt = prompt_map.get("serving", {}).get("prompt", "")
    
    # Generate images only if enabled in settings
    if settings.generate_images:
        prompt_text_map = {
            "featured": featured_prompt,
            "instructions_process": instructions_prompt,
            "serving": serving_prompt,
        }
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
        "topic": recipe.name or "",
        "faq_text": format_faq_text(faq_items),
        "recipe_text": format_recipe_text(recipe),
        "model_name": settings.model_name,
        "temperature": settings.temperature,
        "target_words": settings.target_words,
        "use_multi_call": str(settings.use_multi_call),
        "featured_image_prompt": featured_prompt,
        "instructions_process_image_prompt": instructions_prompt,
        "serving_image_prompt": serving_prompt,
        "WPRM_recipecard_image_prompt": featured_prompt,
        "featured_image_generated_url": generated_urls.get("featured", ""),
        "instructions_process_image_generated_url": generated_urls.get(
            "instructions_process", ""
        ),
        "serving_image_generated_url": generated_urls.get("serving", ""),
        "WPRM_recipe)card_url": generated_urls.get("featured", ""),
    }

    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate recipe batch CSV rows")
    parser.add_argument("--keyword", help="Focus keyword")
    parser.add_argument("--url", action="append", help="Recipe URL (repeatable)")
    parser.add_argument("--input", help="Input CSV with focus_keyword,url columns")
    parser.add_argument("--out", required=True, help="Output CSV path")
    parser.add_argument("--template", help="Template CSV path (optional)")
    parser.add_argument("--log-level", default="INFO", help="Logging level")

    args = parser.parse_args()

    logger = _setup_logger(args.log_level)
    settings = load_settings()

    if args.template:
        if not os.path.exists(args.template):
            logger.error("Template CSV not found: %s", args.template)
            return 1
        headers = load_template_headers(args.template)
    else:
        headers = DEFAULT_HEADERS

    targets: List[Tuple[str, str]] = []
    if args.input:
        targets.extend(_load_input_csv(args.input))
    elif args.keyword and args.url:
        targets.extend([(args.keyword, item) for item in args.url])
    else:
        logger.error("Provide --input or both --keyword and --url")
        return 1

    if not targets:
        logger.error("No valid targets found")
        return 1

    for focus_keyword, url in targets:
        logger.info("Processing %s", url)
        row = _process_recipe(focus_keyword, url, settings, logger)
        if row:
            append_row(args.out, headers, row)
        time.sleep(settings.sleep_seconds)

    logger.info("Done. Output written to %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
