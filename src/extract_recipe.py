import json
import logging
import os
import re
import shutil
import subprocess
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
from bs4 import BeautifulSoup
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import Settings
from .models import Recipe
from .openai_client import responses_create_text


def _clean_text(value: str) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unescape(str(value))).strip()


NAV_NOISE_MARKERS = (
    "see also",
    "read more",
    "leave a comment",
    "cancel reply",
    "latest posts",
    "quick link",
    "privacy policy",
    "terms and conditions",
    "all rights reserved",
    "affiliate disclaimer",
    "about us",
    "contact us",
    "live search",
    "save my name",
    "your email address",
    "required fields",
    "pinterest",
    "instagram",
    "facebook",
)
SECTION_BREAK_MARKERS = (
    "see also",
    "read more",
    "related",
    "categories",
    "latest posts",
    "about us",
    "contact us",
    "privacy policy",
    "terms and conditions",
    "leave a comment",
    "cancel reply",
    "comments",
    "menu",
    "search",
)
INSTRUCTION_START_VERBS = {
    "add",
    "allow",
    "arrange",
    "bake",
    "beat",
    "blend",
    "boil",
    "brush",
    "chill",
    "combine",
    "cook",
    "cool",
    "cut",
    "drain",
    "fold",
    "freeze",
    "grill",
    "heat",
    "knead",
    "let",
    "line",
    "mix",
    "place",
    "pour",
    "preheat",
    "roll",
    "serve",
    "shape",
    "simmer",
    "slice",
    "spread",
    "stir",
    "transfer",
    "wash",
    "whisk",
}
MEASUREMENT_PATTERN = re.compile(
    r"\b(cup|cups|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|"
    r"oz|ounce|ounces|lb|pound|pounds|g|gram|grams|kg|ml|l|clove|cloves|"
    r"slice|slices|can|cans|pinch|dash)\b",
    re.I,
)
INSTRUCTION_ACTION_PATTERN = re.compile(
    r"\b(preheat|mix|stir|whisk|combine|add|bake|cook|boil|simmer|roll|"
    r"place|shape|let|allow|chill|freeze|serve|slice|pour|fold|knead|"
    r"drain|brush|transfer)\b",
    re.I,
)
SECTION_HEADING_PATTERN = re.compile(
    r"^(ingredients?|instructions?|directions?|method|steps?|notes?|nutrition|"
    r"faq|tips?|storage|serving|materials?|definition|benefits?)\b",
    re.I,
)


def _strip_list_prefix(value: str) -> str:
    text = _clean_text(value)
    text = re.sub(r"^[\-\*\u2022]+\s*", "", text)
    text = re.sub(r"^\d+\s*[\).:\-]\s*", "", text)
    text = re.sub(r"^[a-zA-Z]\)\s*", "", text)
    return text.strip()


def _is_noise_line(value: str) -> bool:
    text = _clean_text(value)
    if not text:
        return True
    lowered = text.lower()
    if lowered in {"ingredients", "instructions", "directions", "method"}:
        return True
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return True
    if len(text) > 320:
        return True
    if re.fullmatch(r"[\W_]+", text):
        return True
    if any(marker in lowered for marker in NAV_NOISE_MARKERS):
        return True
    return False


def _looks_like_ingredient(value: str) -> bool:
    text = _strip_list_prefix(value)
    if _is_noise_line(text):
        return False
    lowered = text.lower()
    words = re.findall(r"[a-zA-Z']+", text)
    if not words:
        return False
    if len(words) > 20:
        return False
    if len(text) > 140:
        return False
    if text.endswith(":"):
        return False
    if SECTION_HEADING_PATTERN.search(lowered):
        return False
    if words[0].lower() in INSTRUCTION_START_VERBS:
        return False
    if re.search(r"\b(i|you|we|your|our|my)\b", lowered):
        return False
    if MEASUREMENT_PATTERN.search(lowered) or re.search(r"\d", text):
        return True
    # Allow short ingredient-like lines without quantities, e.g. "fresh parsley"
    return len(words) <= 8 and not text.endswith(".")


def _looks_like_instruction(value: str) -> bool:
    text = _strip_list_prefix(value)
    if _is_noise_line(text):
        return False
    lowered = text.lower()
    words = re.findall(r"[a-zA-Z']+", text)
    if len(words) < 3:
        return False
    if len(words) > 45:
        return False
    if text.endswith(":"):
        return False
    if SECTION_HEADING_PATTERN.search(lowered):
        return False
    if words[0].lower() in {"why", "what", "term", "definition", "categories"}:
        return False
    if words[0].lower() in INSTRUCTION_START_VERBS:
        return True
    if INSTRUCTION_ACTION_PATTERN.search(lowered):
        return True
    return text.endswith(".") and len(words) <= 24


def _clean_recipe_lines(
    items: List[str],
    section_type: str,
    max_items: int = 30,
) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for item in items:
        text = _strip_list_prefix(str(item))
        if not text:
            continue
        if section_type == "ingredients":
            keep = _looks_like_ingredient(text)
        else:
            keep = _looks_like_instruction(text)
        if not keep:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= max_items:
            break
    return cleaned


def _is_section_break(value: str, end_keywords: List[str]) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    lowered = text.lower()
    if any(keyword in lowered for keyword in end_keywords):
        return True
    if any(marker in lowered for marker in SECTION_BREAK_MARKERS):
        return True
    if text.endswith(":") and len(text.split()) <= 4:
        return True
    return False


def _parse_iso8601_duration(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip()
    if not value.startswith("P"):
        return value
    pattern = re.compile(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?"
    )
    match = pattern.match(value)
    if not match:
        return value
    parts: List[str] = []
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    if days:
        parts.append(f"{days} day" + ("s" if days != 1 else ""))
    if hours:
        parts.append(f"{hours} hr" + ("s" if hours != 1 else ""))
    if minutes:
        parts.append(f"{minutes} min")
    return " ".join(parts) if parts else value


def _normalize_to_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        items: List[str] = []
        for item in value:
            if isinstance(item, str):
                items.append(item)
            elif isinstance(item, dict) and "url" in item:
                items.append(item["url"])
        return items
    if isinstance(value, dict):
        if "url" in value:
            return [value["url"]]
        if "@list" in value:
            return [str(v) for v in value.get("@list", [])]
    if isinstance(value, str):
        return [value]
    return []


def _extract_jsonld_blocks(html: str) -> List[Any]:
    soup = BeautifulSoup(html, "lxml")
    blocks: List[Any] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
            blocks.append(data)
        except json.JSONDecodeError:
            continue
    return blocks


def _find_recipe_nodes(node: Any) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    if isinstance(node, dict):
        node_type = node.get("@type") or node.get("type")
        if isinstance(node_type, list):
            type_values = [str(t).lower() for t in node_type]
            is_recipe = any("recipe" == t or "recipe" in t for t in type_values)
        else:
            type_value = str(node_type).lower() if node_type else ""
            is_recipe = "recipe" == type_value or "recipe" in type_value
        if is_recipe:
            matches.append(node)
        if "@graph" in node and isinstance(node["@graph"], list):
            for child in node["@graph"]:
                matches.extend(_find_recipe_nodes(child))
    elif isinstance(node, list):
        for item in node:
            matches.extend(_find_recipe_nodes(item))
    return matches


def _score_recipe_node(node: Dict[str, Any]) -> int:
    keys = [
        "name",
        "recipeIngredient",
        "recipeInstructions",
        "recipeYield",
        "prepTime",
        "cookTime",
        "totalTime",
    ]
    score = 0
    for key in keys:
        if node.get(key):
            score += 1
    return score


def _parse_instructions(value: Any) -> List[str]:
    steps: List[str] = []
    if isinstance(value, list):
        for item in value:
            steps.extend(_parse_instructions(item))
    elif isinstance(value, dict):
        item_type = str(value.get("@type", "")).lower()
        if item_type in {"howtostep", "howtodirection", "howtosection"}:
            if item_type == "howtosection":
                steps.extend(_parse_instructions(value.get("itemListElement")))
            else:
                text = value.get("text") or value.get("name")
                if text:
                    steps.append(_clean_text(str(text)))
        elif "itemListElement" in value:
            steps.extend(_parse_instructions(value.get("itemListElement")))
        elif "text" in value:
            steps.append(_clean_text(str(value.get("text"))))
    elif isinstance(value, str):
        lines = [line.strip() for line in value.split("\n") if line.strip()]
        if len(lines) > 1:
            steps.extend(lines)
        else:
            steps.append(_clean_text(value))
    normalized: List[str] = []
    for step in steps:
        cleaned = _strip_list_prefix(step)
        if cleaned:
            normalized.append(cleaned)
    return [step for step in normalized if step]


def _coerce_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    return str(value)


def _parse_recipe_from_jsonld(html: str, source_url: str) -> Optional[Recipe]:
    blocks = _extract_jsonld_blocks(html)
    recipe_nodes: List[Dict[str, Any]] = []
    for block in blocks:
        recipe_nodes.extend(_find_recipe_nodes(block))
    if not recipe_nodes:
        return None
    recipe_nodes.sort(key=_score_recipe_node, reverse=True)
    data = recipe_nodes[0]

    ingredients = data.get("recipeIngredient")
    if isinstance(ingredients, str):
        ingredients_list = [line.strip() for line in ingredients.split("\n") if line.strip()]
    else:
        ingredients_list = [
            _clean_text(str(item)) for item in (ingredients or []) if str(item).strip()
        ]
    ingredients_list = _clean_recipe_lines(ingredients_list, "ingredients", max_items=40)

    instructions_list = _clean_recipe_lines(
        _parse_instructions(data.get("recipeInstructions")),
        "instructions",
        max_items=30,
    )

    nutrition = data.get("nutrition") or {}
    calories = None
    if isinstance(nutrition, dict):
        calories = _coerce_string(nutrition.get("calories"))

    cuisine = data.get("recipeCuisine") or data.get("cuisineCategory")
    if isinstance(cuisine, list):
        cuisine = ", ".join([str(item) for item in cuisine if item])

    course = data.get("recipeCategory") or data.get("course") or data.get("recipeCourse")
    if isinstance(course, list):
        course = ", ".join([str(item) for item in course if item])

    images = _normalize_to_list(data.get("image"))

    description = data.get("description")
    if isinstance(description, list):
        description = " ".join([str(item) for item in description if item])
    elif isinstance(description, dict):
        description = description.get("text") or description.get("name")

    servings = data.get("recipeYield")
    if isinstance(servings, list):
        servings = ", ".join([str(item) for item in servings if item])
    elif servings is not None and not isinstance(servings, str):
        # Convert integers or other types to string
        servings = str(servings)

    return Recipe(
        name=_clean_text(data.get("name") or "") or None,
        description=_clean_text(description or "") or None,
        servings=servings,
        prep_time=_parse_iso8601_duration(data.get("prepTime")),
        cook_time=_parse_iso8601_duration(data.get("cookTime")),
        total_time=_parse_iso8601_duration(data.get("totalTime")),
        ingredients=ingredients_list,
        instructions=instructions_list,
        calories=calories,
        cuisine=cuisine,
        course=course,
        image_urls=images,
        source_url=source_url,
        extraction_method="jsonld",
    )


def fetch_html(url: str, settings: Settings, logger: logging.Logger) -> Optional[str]:
    def fetch_with_curl() -> Optional[str]:
        curl_path = shutil.which("curl") or "/usr/bin/curl"
        if not curl_path or not Path(curl_path).exists():
            logger.warning("curl not available for fallback fetch")
            return None
        logger.info("Fetching via curl fallback: %s", url)
        env = os.environ.copy()
        env["PATH"] = env.get("PATH", "") + ":/usr/bin:/bin"
        try:
            curl_cmd = [
                curl_path,
                "-Ls",
                "--max-time",
                str(int(settings.request_timeout)),
                "-A",
                settings.user_agent,
            ]
            if (settings.accept_language or "").strip():
                curl_cmd.extend(["-H", f"Accept-Language: {settings.accept_language}"])
            curl_cmd.append(url)
            result = subprocess.run(
                curl_cmd,
                capture_output=True,
                text=True,
                env=env,
            )
        except FileNotFoundError:
            logger.warning("curl not available for fallback fetch")
            return None
        if result.returncode != 0:
            message = (result.stderr or "").strip()
            if message:
                logger.warning("curl fallback failed for %s: %s", url, message)
            return None
        if not (result.stdout or "").strip():
            logger.warning("curl fallback returned empty response for %s", url)
            return None
        return result.stdout or None

    retryer = Retrying(
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    try:
        response = None
        for attempt in retryer:
            with attempt:
                response = requests.get(
                    url,
                    headers={
                        "User-Agent": settings.user_agent,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        **(
                            {"Accept-Language": settings.accept_language}
                            if (settings.accept_language or "").strip()
                            else {}
                        ),
                    },
                    timeout=settings.request_timeout,
                )
                if response.status_code >= 500:
                    raise requests.RequestException(
                        f"Server error: {response.status_code}"
                    )
                break
    except requests.RequestException as exc:
        logger.warning("Request failed for %s: %s", url, exc)
        return fetch_with_curl()
    if response.status_code >= 400:
        logger.warning("Non-success status %s for %s", response.status_code, url)
        return fetch_with_curl()
    return response.text


def _find_list_after_heading(soup: BeautifulSoup, keywords: List[str]) -> List[str]:
    pattern = re.compile("|".join(keywords), re.I)
    for heading in soup.find_all(["h2", "h3", "h4"]):
        heading_text = heading.get_text(" ", strip=True)
        if not pattern.search(heading_text):
            continue
        next_el = heading.find_next_sibling()
        while next_el is not None and next_el.name not in {"ul", "ol"}:
            next_el = next_el.find_next_sibling()
        if next_el is None:
            continue
        items = [
            _clean_text(li.get_text(" ", strip=True))
            for li in next_el.find_all("li")
            if li.get_text(strip=True)
        ]
        if items:
            return items
    return []


def _find_list_by_attr(soup: BeautifulSoup, keywords: List[str]) -> List[str]:
    pattern = re.compile("|".join(keywords), re.I)
    for tag in soup.find_all(["ul", "ol", "section", "div"]):
        attrs = " ".join(
            [
                " ".join(tag.get("class", [])),
                tag.get("id", ""),
                tag.get("data-testid", ""),
            ]
        )
        if not pattern.search(attrs):
            continue
        items = [
            _clean_text(li.get_text(" ", strip=True))
            for li in tag.find_all("li")
            if li.get_text(strip=True)
        ]
        if items:
            return items
    return []


def _section_lines(text: str, start_keywords: List[str], end_keywords: List[str]) -> List[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    start_index = None
    for i, line in enumerate(lines):
        if any(k in line.lower() for k in start_keywords):
            start_index = i
            break
    if start_index is None:
        return []
    section: List[str] = []
    for i in range(start_index + 1, len(lines)):
        line = lines[i]
        if _is_section_break(line, end_keywords):
            break
        section.append(line)
        if len(section) >= 120:
            break
    return [line for line in section if line]


def _fallback_extract_recipe(html: str, source_url: str) -> Recipe:
    try:
        from readability import Document
    except ImportError:
        Document = None

    if Document:
        doc = Document(html)
        title = doc.short_title() or doc.title()
        summary_html = doc.summary(html_partial=True)
    else:
        soup_full = BeautifulSoup(html, "lxml")
        title = soup_full.title.get_text(strip=True) if soup_full.title else None
        summary_html = html
    soup = BeautifulSoup(summary_html, "lxml")

    ingredients = _find_list_after_heading(soup, ["ingredient"])
    if not ingredients:
        ingredients = _find_list_by_attr(soup, ["ingredient"])

    instructions = _find_list_after_heading(soup, ["instruction", "direction", "method"])
    if not instructions:
        instructions = _find_list_by_attr(soup, ["instruction", "direction", "method"])

    text = soup.get_text("\n", strip=True)
    if not ingredients:
        ingredients = _section_lines(
            text,
            ["ingredients"],
            ["instructions", "directions", "method", "steps", "notes", "nutrition"],
        )
    if not instructions:
        instructions = _section_lines(
            text,
            ["instructions", "directions", "method", "steps"],
            ["notes", "nutrition", "faq", "tips", "storage", "serving"],
        )

    ingredients = _clean_recipe_lines(ingredients, "ingredients", max_items=40)
    instructions = _clean_recipe_lines(instructions, "instructions", max_items=30)

    return Recipe(
        name=_clean_text(title) if title else None,
        ingredients=ingredients,
        instructions=instructions,
        source_url=source_url,
        extraction_method="fallback",
    )


def _merge_recipes(primary: Recipe, secondary: Recipe) -> Recipe:
    data = primary.model_dump()
    secondary_data = secondary.model_dump()
    for key, value in secondary_data.items():
        if data.get(key) in (None, "", []) and value not in (None, "", []):
            data[key] = value
    data["extraction_method"] = primary.extraction_method
    return Recipe(**data)


def extract_recipe_from_html(
    html: str,
    source_url: str,
    settings: Settings,
    logger: logging.Logger,
    gpt_fallback: bool = True,
) -> Recipe:
    """
    Extract recipe data from HTML content using multiple extraction strategies.
    
    This function attempts to extract recipe information using the following
    strategies in order of reliability:
    1. JSON-LD structured data extraction (most reliable, fastest)
    2. HTML fallback parsing (medium reliability, no API calls)
    3. GPT-based extraction (if enabled and API key available, most flexible)
    
    The function merges results from multiple strategies to maximize data extraction.
    If a strategy fails to extract certain fields, results from other strategies
    are used to fill in the gaps.
    
    Args:
        html: Raw HTML content from the recipe page
        source_url: Original URL of the recipe (used for reference and image URLs)
        settings: Application settings including API keys and configuration
        logger: Logger instance for recording extraction process and errors
        gpt_fallback: Whether to use GPT extraction if other methods fail or
                     produce incomplete results. Defaults to True.
    
    Returns:
        Recipe object with extracted data. Fields may be None if not found.
        The extraction_method field indicates which method(s) were used.
    
    Example:
        >>> html = fetch_html("https://example.com/recipe")
        >>> recipe = extract_recipe_from_html(
        ...     html,
        ...     "https://example.com/recipe",
        ...     settings,
        ...     logger
        ... )
        >>> print(f"Recipe: {recipe.name}")
        >>> print(f"Extraction method: {recipe.extraction_method}")
        Recipe: Chocolate Chip Cookies
        Extraction method: jsonld
    """
    jsonld_recipe = _parse_recipe_from_jsonld(html, source_url)
    fallback_recipe = _fallback_extract_recipe(html, source_url)

    if jsonld_recipe:
        recipe = _merge_recipes(jsonld_recipe, fallback_recipe)
    else:
        recipe = fallback_recipe

    if (not recipe.ingredients or not recipe.instructions) and gpt_fallback:
        if settings.openai_api_key:
            gpt_recipe = _extract_recipe_with_gpt(html, settings, logger)
            if gpt_recipe:
                recipe = _merge_recipes(recipe, gpt_recipe)
                recipe.extraction_method = "gpt_fallback"
        else:
            logger.info("OPENAI_API_KEY not set; skipping GPT fallback")

    return recipe


def _extract_recipe_with_gpt(
    html: str, settings: Settings, logger: logging.Logger
) -> Optional[Recipe]:
    try:
        from readability import Document
    except ImportError:
        Document = None

    if Document:
        doc = Document(html)
        summary_html = doc.summary(html_partial=True)
        text = BeautifulSoup(summary_html, "lxml").get_text(" ", strip=True)
    else:
        text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    if len(text) > 12000:
        text = text[:12000]

    prompt = (
        "Extract recipe data from the article text below. Only use information explicitly "
        "present in the text. If a field is missing, use an empty string or an empty list. "
        "Return ONLY JSON with keys: name, description, servings, prep_time, cook_time, "
        "total_time, ingredients, instructions, calories, cuisine, course, notes."
    )

    payload = {
        "model": settings.model_name,
        "input": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
        "max_output_tokens": 800,
    }

    output_text = responses_create_text(settings, payload, logger)
    if not output_text:
        return None

    json_text = _extract_json_from_text(output_text)
    if not json_text:
        logger.warning("GPT recipe extraction returned no JSON")
        return None

    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        logger.warning("GPT recipe extraction returned invalid JSON")
        return None

    def clean(value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            return ", ".join(str(item).strip() for item in value if str(item).strip())
        if isinstance(value, str) and value.strip().lower() in {"not provided", "unknown", "n/a"}:
            return None
        return value

    def normalize_list(value):
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.split("\n") if item.strip()]
        return [str(value).strip()] if str(value).strip() else []

    cleaned_ingredients = _clean_recipe_lines(
        normalize_list(payload.get("ingredients")),
        "ingredients",
        max_items=40,
    )
    cleaned_instructions = _clean_recipe_lines(
        normalize_list(payload.get("instructions")),
        "instructions",
        max_items=30,
    )

    return Recipe(
        name=clean(payload.get("name")),
        description=clean(payload.get("description")),
        servings=clean(payload.get("servings")),
        prep_time=clean(payload.get("prep_time")),
        cook_time=clean(payload.get("cook_time")),
        total_time=clean(payload.get("total_time")),
        ingredients=cleaned_ingredients,
        instructions=cleaned_instructions,
        calories=clean(payload.get("calories")),
        cuisine=clean(payload.get("cuisine")),
        course=clean(payload.get("course")),
        notes=clean(payload.get("notes")),
        extraction_method="gpt_fallback",
    )


def _extract_json_from_text(text: str) -> Optional[str]:
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not match:
        return None
    return match.group(1)
