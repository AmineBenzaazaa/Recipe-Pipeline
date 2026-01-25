import json
import logging
import re
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import Settings
from .models import Recipe
from .openai_client import responses_create_text

REQUIRED_FIELDS = [
    "prep_time",
    "cook_time",
    "total_time",
    "servings",
    "calories",
    "cuisine",
    "course",
]

LABEL_STOP_PATTERN = re.compile(
    r"(prep time|cook time|total time|servings|yield|calories|cuisine|course|ingredients|instructions|directions|notes|nutrition)",
    re.I,
)
TIME_PATTERN = re.compile(
    r"(?P<num>\d+(?:\s*-\s*\d+)?)\s*(?P<unit>hr|hrs|hour|hours|min|mins|minute|minutes)",
    re.I,
)
INVALID_LABEL_TOKENS = {
    "contact",
    "instagram",
    "pinterest",
    "facebook",
    "recipe",
    "recipes",
    "newsletter",
    "privacy",
    "cookies",
    "baked",
    "baking",
}


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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
    parts = []
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


def _get_text(html: str) -> str:
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
    return _normalize_whitespace(text)


def _extract_labeled_value(text: str, labels: list[str]) -> Optional[str]:
    label_pattern = "|".join([re.escape(label) for label in labels])
    pattern = re.compile(rf"(?:{label_pattern})\s*[:\-]?\s*(?P<value>.{{1,80}})", re.I)
    match = pattern.search(text)
    if not match:
        return None
    value = match.group("value")
    value = LABEL_STOP_PATTERN.split(value)[0]
    value = value.strip(" .-|·:")
    if len(value) > 60:
        value = value[:60]
    return _normalize_whitespace(value) if value else None


def _normalize_time(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = _normalize_whitespace(value.lower())
    cleaned = cleaned.replace("&", " ")
    match = TIME_PATTERN.search(cleaned)
    if not match:
        return None
    num = match.group("num").replace(" ", "")
    unit = match.group("unit").lower()
    unit = "hr" if unit.startswith("h") else "min"
    return f"{num} {unit}"


def _normalize_servings(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = _normalize_whitespace(value)
    match = re.search(r"\d+", cleaned)
    if not match:
        return None
    count = int(match.group())
    if count > 100:
        return None
    return f"{count} servings"


def _normalize_calories(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = _normalize_whitespace(value)
    digits = re.search(r"\d+", cleaned)
    if not digits:
        return None
    count = int(digits.group())
    if count > 5000:
        return None
    return f"{count} calories"


def _normalize_title(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = _normalize_whitespace(value)
    lowered = cleaned.lower()
    if any(token in lowered for token in INVALID_LABEL_TOKENS):
        return None
    if any(char.isdigit() for char in cleaned):
        return None
    if len(cleaned) > 40:
        return None
    if len(cleaned.split()) > 3:
        return None
    return cleaned.title()


def _extract_metadata_from_html(html: str) -> Dict[str, Optional[str]]:
    soup = BeautifulSoup(html, "lxml")

    def itemprop_value(name: str) -> Optional[str]:
        tag = soup.find(attrs={"itemprop": name})
        if not tag:
            return None
        value = tag.get("content") or tag.get_text(" ", strip=True)
        return _normalize_whitespace(value) if value else None

    def class_value(pattern: str) -> Optional[str]:
        tag = soup.find(class_=re.compile(pattern, re.I))
        if not tag:
            return None
        return _normalize_whitespace(tag.get_text(" ", strip=True))

    prep_raw = itemprop_value("prepTime") or class_value(r"prep[-_ ]time")
    cook_raw = itemprop_value("cookTime") or class_value(r"cook[-_ ]time")
    total_raw = itemprop_value("totalTime") or class_value(r"total[-_ ]time")

    prep_raw = _parse_iso8601_duration(prep_raw)
    cook_raw = _parse_iso8601_duration(cook_raw)
    total_raw = _parse_iso8601_duration(total_raw)

    return {
        "prep_time": prep_raw,
        "cook_time": cook_raw,
        "total_time": total_raw,
        "servings": itemprop_value("recipeYield") or class_value(r"(servings|yield)"),
        "calories": itemprop_value("calories"),
        "cuisine": itemprop_value("recipeCuisine"),
        "course": itemprop_value("recipeCategory"),
    }


def extract_metadata_from_text(text: str) -> Dict[str, Optional[str]]:
    return {
        "prep_time": _normalize_time(
            _extract_labeled_value(text, ["prep time", "preparation time", "prep"]) 
        ),
        "cook_time": _normalize_time(
            _extract_labeled_value(text, ["cook time", "cooking time", "cook"]) 
        ),
        "total_time": _normalize_time(
            _extract_labeled_value(text, ["total time", "total"]) 
        ),
        "servings": _normalize_servings(
            _extract_labeled_value(text, ["servings", "serves", "yield", "makes"]) 
        ),
        "calories": _normalize_calories(
            _extract_labeled_value(text, ["calories", "calorie", "kcal"]) 
        ),
        "cuisine": _normalize_title(_extract_labeled_value(text, ["cuisine"])) ,
        "course": _normalize_title(_extract_labeled_value(text, ["course", "category"])) ,
    }


def _sanitize_metadata(data: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
    return {
        "prep_time": _normalize_time(data.get("prep_time")),
        "cook_time": _normalize_time(data.get("cook_time")),
        "total_time": _normalize_time(data.get("total_time")),
        "servings": _normalize_servings(data.get("servings")),
        "calories": _normalize_calories(data.get("calories")),
        "cuisine": _normalize_title(data.get("cuisine")),
        "course": _normalize_title(data.get("course")),
    }


def _request_with_retry(settings: Settings, method: str, url: str, **kwargs) -> requests.Response:
    retryer = Retrying(
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    for attempt in retryer:
        with attempt:
            response = requests.request(method, url, **kwargs)
            if response.status_code >= 500:
                raise requests.RequestException(f"Server error: {response.status_code}")
            return response
    raise requests.RequestException("Failed to complete request after retries")


def _search_context(settings: Settings, query: str, logger: logging.Logger) -> str:
    context_lines = []
    if settings.serper_api_key:
        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"}
        payload = {"q": query}
        try:
            response = _request_with_retry(
                settings, "POST", url, headers=headers, json=payload, timeout=settings.request_timeout
            )
            data = response.json()
            for item in (data.get("organic") or [])[:3]:
                title = item.get("title")
                snippet = item.get("snippet")
                link = item.get("link")
                if title and snippet:
                    context_lines.append(f"{title} - {snippet} ({link})")
        except requests.RequestException as exc:
            logger.warning("Serper metadata search failed: %s", exc)
    elif settings.serpapi_api_key:
        url = "https://serpapi.com/search.json"
        params = {"engine": "google", "q": query, "api_key": settings.serpapi_api_key}
        try:
            response = _request_with_retry(
                settings, "GET", url, params=params, timeout=settings.request_timeout
            )
            data = response.json()
            for item in (data.get("organic_results") or [])[:3]:
                title = item.get("title")
                snippet = item.get("snippet")
                link = item.get("link")
                if title and snippet:
                    context_lines.append(f"{title} - {snippet} ({link})")
        except requests.RequestException as exc:
            logger.warning("SerpAPI metadata search failed: %s", exc)
    return "\n".join(context_lines)


def _gpt_enrich_metadata(
    recipe: Recipe,
    focus_keyword: str,
    search_context: str,
    settings: Settings,
    logger: logging.Logger,
) -> Dict[str, Optional[str]]:
    if not settings.openai_api_key:
        return {}
    context = {
        "name": recipe.name,
        "description": recipe.description,
        "ingredients": recipe.ingredients[:20],
        "instructions": recipe.instructions[:10],
        "existing": {
            "prep_time": recipe.prep_time,
            "cook_time": recipe.cook_time,
            "total_time": recipe.total_time,
            "servings": recipe.servings,
            "calories": recipe.calories,
            "cuisine": recipe.cuisine,
            "course": recipe.course,
        },
        "search_context": search_context,
    }

    prompt = (
        "Fill recipe metadata fields with realistic values. Use the focus keyword, recipe context, "
        "and search context if present. Return JSON with keys: prep_time, cook_time, total_time, "
        "servings, calories, cuisine, course. Always provide a value for each key; do not use "
        "'not provided' or null. If you must infer, provide a reasonable estimate. Use units "
        "like 'min', 'hr', 'servings', and 'calories'."
    )

    payload = {
        "model": settings.model_name,
        "input": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"Focus keyword: {focus_keyword}\nContext: {json.dumps(context)}",
            },
        ],
        "max_output_tokens": 400,
    }

    output_text = responses_create_text(settings, payload, logger)
    match = re.search(r"(\{.*\})", output_text, re.DOTALL)
    if not match:
        logger.warning("Metadata enrichment response did not include JSON")
        return {}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.warning("Metadata enrichment JSON invalid")
        return {}

    return _sanitize_metadata(payload)


def _default_metadata(recipe: Recipe, focus_keyword: str) -> Dict[str, str]:
    name = (recipe.name or focus_keyword or "").lower()
    if "cookie" in name or "brownie" in name or "cake" in name or "dessert" in name:
        return {
            "prep_time": "15 min",
            "cook_time": "12 min",
            "total_time": "27 min",
            "servings": "24 servings",
            "calories": "180 calories",
            "cuisine": "American",
            "course": "Dessert",
        }
    if "soup" in name or "stew" in name:
        return {
            "prep_time": "15 min",
            "cook_time": "25 min",
            "total_time": "40 min",
            "servings": "4 servings",
            "calories": "250 calories",
            "cuisine": "American",
            "course": "Soup",
        }
    if "salad" in name:
        return {
            "prep_time": "15 min",
            "cook_time": "0 min",
            "total_time": "15 min",
            "servings": "4 servings",
            "calories": "200 calories",
            "cuisine": "American",
            "course": "Salad",
        }
    return {
        "prep_time": "15 min",
        "cook_time": "20 min",
        "total_time": "35 min",
        "servings": "4 servings",
        "calories": "300 calories",
        "cuisine": "American",
        "course": "Main Course",
    }


def enrich_recipe_metadata(
    recipe: Recipe,
    html: str,
    focus_keyword: str,
    settings: Settings,
    logger: logging.Logger,
) -> Recipe:
    text = _get_text(html)
    extracted = extract_metadata_from_text(text)
    html_extracted = _extract_metadata_from_html(html)

    data = recipe.model_dump()
    combined = {**html_extracted, **extracted}
    for key, value in combined.items():
        if not data.get(key) and value:
            data[key] = value

    cleaned = _sanitize_metadata(data)
    for key, value in cleaned.items():
        data[key] = value

    missing = [field for field in REQUIRED_FIELDS if not data.get(field)]
    if missing and not settings.skip_metadata_enrichment:
        query = recipe.name or focus_keyword
        search_context = _search_context(settings, f"{query} recipe prep time cook time servings calories", logger)
        enriched = _gpt_enrich_metadata(recipe, focus_keyword, search_context, settings, logger)
        for key in REQUIRED_FIELDS:
            if not data.get(key) and enriched.get(key):
                data[key] = enriched[key]
    elif missing:
        logger.info("Metadata enrichment skipped - using defaults for missing fields")

    missing = [field for field in REQUIRED_FIELDS if not data.get(field)]
    if missing:
        defaults = _default_metadata(recipe, focus_keyword)
        for key in missing:
            data[key] = defaults.get(key)

    return Recipe(**data)
