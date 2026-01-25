import json
import logging
import re
from typing import List

import requests
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import Settings
from .models import FAQItem, Recipe
from .openai_client import responses_create_text


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


def _serper_faqs(query: str, settings: Settings, logger: logging.Logger) -> List[FAQItem]:
    if not settings.serper_api_key:
        return []
    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"}
    payload = {"q": query}
    try:
        response = _request_with_retry(
            settings,
            "POST",
            url,
            headers=headers,
            json=payload,
            timeout=settings.request_timeout,
        )
    except requests.RequestException as exc:
        logger.warning("Serper request failed: %s", exc)
        return []
    if response.status_code >= 400:
        logger.warning("Serper status %s", response.status_code)
        return []
    data = response.json()
    faqs = []
    for item in data.get("peopleAlsoAsk", []) or []:
        question = item.get("question")
        answer = item.get("snippet") or item.get("answer")
        if question and answer:
            faqs.append(FAQItem(question=question.strip(), answer=answer.strip()))
    return faqs


def _serpapi_faqs(query: str, settings: Settings, logger: logging.Logger) -> List[FAQItem]:
    if not settings.serpapi_api_key:
        return []
    url = "https://serpapi.com/search.json"
    params = {"engine": "google", "q": query, "api_key": settings.serpapi_api_key}
    try:
        response = _request_with_retry(
            settings, "GET", url, params=params, timeout=settings.request_timeout
        )
    except requests.RequestException as exc:
        logger.warning("SerpAPI request failed: %s", exc)
        return []
    if response.status_code >= 400:
        logger.warning("SerpAPI status %s", response.status_code)
        return []
    data = response.json()
    faqs = []
    for item in data.get("related_questions", []) or data.get("people_also_ask", []) or []:
        question = item.get("question")
        answer = item.get("snippet") or item.get("answer")
        if question and answer:
            faqs.append(FAQItem(question=question.strip(), answer=answer.strip()))
    return faqs


def _extract_json_from_text(text: str) -> str:
    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    return match.group(1) if match else ""


def _gpt_faqs(
    focus_keyword: str, recipe: Recipe, settings: Settings, logger: logging.Logger
) -> List[FAQItem]:
    if not settings.openai_api_key:
        logger.info("OPENAI_API_KEY not set; skipping GPT FAQ fallback")
        return []
    recipe_context = {
        "name": recipe.name,
        "ingredients": recipe.ingredients[:15],
        "instructions": recipe.instructions[:8],
        "servings": recipe.servings,
        "cuisine": recipe.cuisine,
        "course": recipe.course,
    }

    prompt = (
        "Generate 6-10 FAQ Q/A pairs for a recipe article. Questions should be natural and "
        "related to the focus keyword and the recipe details. Answers must be 2-4 sentences, "
        "accurate, and not speculative. Return ONLY JSON as a list of objects with keys "
        "question and answer."
    )

    payload = {
        "model": settings.model_name,
        "input": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"Focus keyword: {focus_keyword}\nRecipe context: {json.dumps(recipe_context)}",
            },
        ],
        "max_output_tokens": 900,
    }

    output_text = responses_create_text(settings, payload, logger)
    json_text = _extract_json_from_text(output_text)
    if not json_text:
        logger.warning("GPT FAQ response did not include JSON")
        return []

    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        logger.warning("GPT FAQ response JSON invalid")
        return []

    faqs = []
    if isinstance(payload, list):
        for item in payload:
            question = item.get("question")
            answer = item.get("answer")
            if question and answer:
                faqs.append(FAQItem(question=question.strip(), answer=answer.strip()))
    return faqs


def get_faqs(
    focus_keyword: str,
    recipe: Recipe,
    settings: Settings,
    logger: logging.Logger,
) -> List[FAQItem]:
    query = focus_keyword
    if recipe.name and recipe.name.lower() not in focus_keyword.lower():
        query = f"{focus_keyword} {recipe.name}"

    faqs = _serper_faqs(query, settings, logger)
    if not faqs:
        faqs = _serpapi_faqs(query, settings, logger)

    seen = set()
    deduped: List[FAQItem] = []
    for item in faqs:
        if item.question.lower() in seen:
            continue
        seen.add(item.question.lower())
        deduped.append(item)

    if len(deduped) < 6 and not settings.skip_gpt_faqs:
        gpt_items = _gpt_faqs(focus_keyword, recipe, settings, logger)
        for item in gpt_items:
            if item.question.lower() in seen:
                continue
            seen.add(item.question.lower())
            deduped.append(item)
    elif len(deduped) < 6:
        logger.info("GPT FAQ generation skipped - returning available FAQs from search APIs")

    return deduped[:10]
