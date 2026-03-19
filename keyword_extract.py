#!/usr/bin/env python3
import argparse
import csv
import io
import json
import logging
import os
import re
import sys
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

from src.config import load_settings
from src.openai_client import responses_create_text

BLOCKED_DOMAINS = {
    "pinterest.com",
    "www.pinterest.com",
    "pin.it",
    "i.pinimg.com",
    "pinimg.com",
    "instagram.com",
    "facebook.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "youtube.com",
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "or",
    "the",
    "of",
    "to",
    "for",
    "with",
    "in",
    "on",
    "recipe",
    "easy",
    "best",
    "simple",
    "quick",
    "homemade",
}

WORD_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9'_-]*")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

PET_HINTS = {
    "dog",
    "dogs",
    "puppy",
    "puppies",
    "pup",
    "canine",
    "pet",
}

PROMO_HINTS = {
    "best",
    "ultimate",
    "incredible",
    "amazing",
    "easy",
    "guide",
    "tips",
    "ways",
}

RECIPE_HINTS = ("recipe", "ingredients", "instructions", "cook", "bake", "prep")


def setup_logger(level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger("keyword_extract")


def normalize_keyword_phrase(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    text = text.strip("\"'`")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def read_keywords(file_path: str, repeated_keywords: List[str], split_commas: bool = False) -> List[str]:
    values: List[str] = []
    for value in repeated_keywords:
        cleaned = normalize_keyword_phrase(value)
        if cleaned:
            values.append(cleaned)

    if file_path:
        with open(file_path, "r", encoding="utf-8") as handle:
            for line in handle:
                cleaned = normalize_keyword_phrase(line)
                if not cleaned:
                    continue
                if split_commas and "," in cleaned and "http" not in cleaned:
                    for token in cleaned.split(","):
                        part = normalize_keyword_phrase(token)
                        if part:
                            values.append(part)
                else:
                    values.append(cleaned)

    deduped: List[str] = []
    seen = set()
    for item in values:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def normalize_url(url: str) -> str:
    if not url:
        return ""
    candidate = url.strip()
    if not candidate:
        return ""

    parsed = urllib.parse.urlparse(candidate)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        redirect_target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        if redirect_target:
            candidate = urllib.parse.unquote(redirect_target)
            parsed = urllib.parse.urlparse(candidate)

    if parsed.scheme not in {"http", "https"}:
        return ""
    if not parsed.netloc:
        return ""
    return candidate


def is_blocked(url: str) -> bool:
    if not url:
        return True
    netloc = urllib.parse.urlparse(url).netloc.lower()
    if not netloc:
        return True
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return any(netloc == domain or netloc.endswith(f".{domain}") for domain in BLOCKED_DOMAINS)


def clean_title(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    for sep in ("|", " - ", " — ", " :: "):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
    text = re.sub(r"\brecipe\b$", "", text, flags=re.I).strip()
    return text


def keyword_token_set(value: str) -> Set[str]:
    return {
        token
        for token in extract_keywords(value, limit=30)
        if token and token not in STOPWORDS
    }


def overlap_ratio(query: str, candidate: str) -> float:
    query_tokens = keyword_token_set(query)
    if not query_tokens:
        return 0.0
    candidate_tokens = keyword_token_set(candidate)
    if not candidate_tokens:
        return 0.0
    return len(query_tokens & candidate_tokens) / len(query_tokens)


def extract_keywords(value: str, limit: int = 8) -> List[str]:
    tokens: List[str] = []
    seen = set()
    for match in WORD_RE.findall(value.lower()):
        token = match.strip("'-_")
        if not token or token in STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= limit:
            break
    return tokens


def looks_recipeish(item: Dict[str, str]) -> bool:
    text = " ".join(
        [
            item.get("title", "").lower(),
            item.get("snippet", "").lower(),
            urllib.parse.urlparse(item.get("url", "")).path.lower(),
        ]
    )
    return any(token in text for token in RECIPE_HINTS)


def extract_recipe_nodes(payload: Any) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            type_value = value.get("@type")
            types: List[str] = []
            if isinstance(type_value, list):
                types = [str(item).lower() for item in type_value]
            elif type_value:
                types = [str(type_value).lower()]
            if any("recipe" == item or item.endswith(":recipe") or "recipe" in item for item in types):
                nodes.append(value)
            for child in value.values():
                _walk(child)
            return
        if isinstance(value, list):
            for child in value:
                _walk(child)

    _walk(payload)
    return nodes


def _instruction_count(value: Any) -> int:
    if isinstance(value, list):
        count = 0
        for item in value:
            if isinstance(item, str) and item.strip():
                count += 1
            elif isinstance(item, dict) and str(item.get("text", "")).strip():
                count += 1
            elif isinstance(item, list):
                count += _instruction_count(item)
        return count
    if isinstance(value, dict):
        if str(value.get("text", "")).strip():
            return 1
    return 0


def fetch_recipe_page_signals(
    url: str,
    timeout: float,
    query: str,
    pet_mode: bool,
    logger: logging.Logger,
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "schema_recipe_name": "",
        "page_title": "",
        "has_recipe_schema": False,
        "ingredient_count": 0,
        "instruction_count": 0,
        "quality_score": 0.0,
    }
    if not url:
        return metadata

    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        html = response.text or ""
    except Exception as exc:
        logger.debug("Page fetch failed for %s: %s", url, exc)
        return metadata

    if not html:
        return metadata

    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    metadata["page_title"] = clean_title(title_tag.get_text(" ", strip=True)) if title_tag else ""

    recipe_nodes: List[Dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        recipe_nodes.extend(extract_recipe_nodes(payload))

    best_schema_name = ""
    best_ingredients = 0
    best_instructions = 0
    best_schema_score = -1
    for node in recipe_nodes:
        schema_name = clean_title(str(node.get("name") or ""))
        ingredients = node.get("recipeIngredient")
        instructions = node.get("recipeInstructions")
        ingredient_count = 0
        if isinstance(ingredients, list):
            ingredient_count = len([item for item in ingredients if str(item).strip()])
        instruction_count = _instruction_count(instructions)
        schema_score = (
            (4 if schema_name else 0)
            + min(ingredient_count, 10) * 0.4
            + min(instruction_count, 10) * 0.5
        )
        if schema_score > best_schema_score:
            best_schema_score = schema_score
            best_schema_name = schema_name
            best_ingredients = ingredient_count
            best_instructions = instruction_count

    if best_schema_score >= 0:
        metadata["schema_recipe_name"] = best_schema_name
        metadata["has_recipe_schema"] = True
        metadata["ingredient_count"] = best_ingredients
        metadata["instruction_count"] = best_instructions

    candidate_name = metadata["schema_recipe_name"] or metadata["page_title"]
    score = 0.0
    if metadata["has_recipe_schema"]:
        score += 5.0
    score += min(int(metadata["ingredient_count"]), 8) * 0.4
    score += min(int(metadata["instruction_count"]), 8) * 0.4
    score += overlap_ratio(query, candidate_name) * 4.0
    lowered = f"{candidate_name} {url}".lower()
    if looks_recipeish({"title": candidate_name, "snippet": "", "url": url}):
        score += 1.2
    if pet_mode and any(term in lowered for term in PET_HINTS):
        score += 1.4
    if any(term in lowered for term in PROMO_HINTS):
        score -= 0.8
    metadata["quality_score"] = round(score, 3)
    return metadata


def enrich_results_with_page_signals(
    results: List[Dict[str, str]],
    query: str,
    timeout: float,
    pet_mode: bool,
    logger: logging.Logger,
    max_enriched: int = 5,
) -> List[Dict[str, str]]:
    enriched: List[Dict[str, str]] = []
    for idx, item in enumerate(results):
        copy_item = dict(item)
        copy_item.setdefault("quality_score", 0.0)
        if idx < max_enriched:
            signals = fetch_recipe_page_signals(
                url=copy_item.get("url", ""),
                timeout=timeout,
                query=query,
                pet_mode=pet_mode,
                logger=logger,
            )
            for key, value in signals.items():
                copy_item[key] = value
            if copy_item.get("schema_recipe_name"):
                copy_item["title"] = copy_item.get("schema_recipe_name", "")
            elif copy_item.get("page_title"):
                copy_item["title"] = copy_item.get("page_title", "")
        else:
            base = 1.0 if looks_recipeish(copy_item) else 0.0
            base += overlap_ratio(query, copy_item.get("title", "")) * 2.5
            lowered = f"{copy_item.get('title', '')} {copy_item.get('snippet', '')}".lower()
            if pet_mode and any(term in lowered for term in PET_HINTS):
                base += 0.8
            copy_item["quality_score"] = round(base, 3)
        copy_item["title"] = clean_title(copy_item.get("title", ""))
        enriched.append(copy_item)

    enriched.sort(key=lambda item: float(item.get("quality_score", 0.0)), reverse=True)
    return enriched


def dedupe_results(items: List[Dict[str, str]], max_results: int) -> List[Dict[str, str]]:
    ranked = sorted(items, key=lambda item: (not looks_recipeish(item),))
    unique: List[Dict[str, str]] = []
    seen = set()
    for item in ranked:
        url = normalize_url(item.get("url", ""))
        if not url or is_blocked(url):
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        title = clean_title(item.get("title", "")) or url
        unique.append(
            {
                "title": title,
                "url": url,
                "snippet": (item.get("snippet") or "").strip(),
                "quality_score": 0.0,
            }
        )
        if len(unique) >= max_results:
            break
    return unique


def search_serper(query: str, api_key: str, timeout: float, max_results: int) -> List[Dict[str, str]]:
    response = requests.post(
        "https://google.serper.dev/search",
        headers={
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        },
        json={"q": query, "num": max_results},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json() or {}
    results = []
    for item in data.get("organic", []) or []:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
        )
    return dedupe_results(results, max_results=max_results)


def search_serpapi(query: str, api_key: str, timeout: float, max_results: int) -> List[Dict[str, str]]:
    response = requests.get(
        "https://serpapi.com/search.json",
        params={"engine": "google", "q": query, "api_key": api_key, "num": max_results},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json() or {}
    results = []
    for item in data.get("organic_results", []) or []:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
        )
    return dedupe_results(results, max_results=max_results)


def search_duckduckgo(query: str, timeout: float, max_results: int) -> List[Dict[str, str]]:
    response = requests.get(
        "https://duckduckgo.com/html/",
        params={"q": query},
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
        },
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    results: List[Dict[str, str]] = []
    for block in soup.select(".result"):
        link = block.select_one(".result__a")
        if not link:
            continue
        snippet_node = block.select_one(".result__snippet")
        results.append(
            {
                "title": link.get_text(" ", strip=True),
                "url": link.get("href", ""),
                "snippet": snippet_node.get_text(" ", strip=True) if snippet_node else "",
            }
        )
    return dedupe_results(results, max_results=max_results)


def detect_pet_mode(keywords: List[str]) -> bool:
    if not keywords:
        return False
    tagged = 0
    for item in keywords:
        lowered = item.lower()
        if any(term in lowered for term in PET_HINTS):
            tagged += 1
    return tagged >= max(1, int(len(keywords) * 0.35))


def build_search_query(keyword: str, context_hint: str, pet_mode: bool) -> str:
    base = normalize_keyword_phrase(keyword)
    if not base:
        return ""
    lowered = base.lower()
    if context_hint.strip():
        hint = context_hint.strip()
        if hint.lower() not in lowered:
            base = f"{base} {hint}"
            lowered = base.lower()
    if "recipe" not in lowered:
        base = f"{base} recipe"
        lowered = base.lower()
    if pet_mode and not any(term in lowered for term in PET_HINTS):
        base = f"{base} for dogs"
    return base


def search_keyword(
    search_query: str,
    settings,
    timeout: float,
    max_results: int,
    logger: logging.Logger,
) -> Tuple[str, List[Dict[str, str]]]:
    query_variants = [search_query]
    lowered = search_query.lower()
    if " for dogs" in lowered:
        query_variants.append(re.sub(r"\s+for dogs\b", "", search_query, flags=re.I).strip())
    if " recipe" in lowered:
        query_variants.append(re.sub(r"\s+recipe\b", "", search_query, flags=re.I).strip())

    providers = []
    if settings.serper_api_key:
        providers.append(("serper", lambda q: search_serper(q, settings.serper_api_key, timeout, max_results)))
    if settings.serpapi_api_key:
        providers.append(("serpapi", lambda q: search_serpapi(q, settings.serpapi_api_key, timeout, max_results)))
    providers.append(("duckduckgo", lambda q: search_duckduckgo(q, timeout, max_results)))

    for variant in query_variants:
        if not variant:
            continue
        for name, runner in providers:
            try:
                results = runner(variant)
                if results:
                    return name, results
            except Exception as exc:
                logger.warning("Search provider %s failed for '%s': %s", name, variant, exc)

    return "none", []


def parse_json_object(text: str) -> Dict[str, object]:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def pick_with_openai(
    query: str,
    results: List[Dict[str, str]],
    model: str,
    settings,
    logger: logging.Logger,
) -> Optional[Dict[str, object]]:
    if not settings.openai_api_key or not results:
        return None

    compact_results = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", ""),
            "has_recipe_schema": bool(item.get("has_recipe_schema", False)),
            "ingredient_count": int(item.get("ingredient_count", 0) or 0),
            "instruction_count": int(item.get("instruction_count", 0) or 0),
            "quality_score": float(item.get("quality_score", 0.0) or 0.0),
        }
        for item in results[:8]
    ]
    prompt = (
        "Choose the single best recipe page for the keyword based only on provided search results.\n"
        "Prefer pages that are real recipe articles with actual ingredients and instructions.\n"
        "Strongly avoid category pages, listicles, roundups, or non-recipe pages.\n"
        "Keep recipe_name concise and close to the keyword intent. No clickbait phrasing.\n"
        "Return strict JSON with keys: recipe_name, recipe_url, keywords.\n"
        "keywords must be 4-10 short lowercase terms.\n"
        f"Keyword: {query}\n"
        f"Search results JSON: {json.dumps(compact_results, ensure_ascii=True)}"
    )
    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
        "temperature": 0.2,
        "max_output_tokens": 320,
    }
    output_text = responses_create_text(settings, payload, logger)
    parsed = parse_json_object(output_text)
    if not parsed:
        return None

    allowed_urls = {item.get("url", "") for item in compact_results}
    recipe_url = normalize_url(str(parsed.get("recipe_url") or ""))
    if not recipe_url or recipe_url not in allowed_urls or is_blocked(recipe_url):
        return None

    recipe_name = clean_title(str(parsed.get("recipe_name") or ""))
    keywords = parsed.get("keywords")
    normalized_keywords: List[str] = []
    if isinstance(keywords, list):
        for item in keywords:
            if isinstance(item, str) and item.strip():
                normalized_keywords.append(item.strip().lower())
    elif isinstance(keywords, str):
        for item in keywords.split(","):
            part = item.strip().lower()
            if part:
                normalized_keywords.append(part)

    if not recipe_name:
        for item in compact_results:
            if item.get("url") == recipe_url:
                recipe_name = clean_title(item.get("title", ""))
                break

    return {
        "recipe_name": recipe_name,
        "recipe_url": recipe_url,
        "keywords": normalized_keywords,
    }


def fallback_pick(query: str, results: List[Dict[str, str]]) -> Dict[str, object]:
    if results:
        best = max(results, key=lambda item: float(item.get("quality_score", 0.0) or 0.0))
        recipe_name = clean_title(best.get("title", "")) or normalize_keyword_phrase(query)
        recipe_url = best.get("url", "")
    else:
        recipe_name = normalize_keyword_phrase(query)
        recipe_url = ""
    return {
        "recipe_name": recipe_name,
        "recipe_url": recipe_url,
        "keywords": extract_keywords(query),
    }


def choose_focus_keyword(query: str, picked_name: str) -> str:
    normalized_query = normalize_keyword_phrase(query)
    if not normalized_query:
        return clean_title(picked_name) or ""
    candidate = clean_title(picked_name)
    if not candidate:
        return normalized_query
    if overlap_ratio(normalized_query, candidate) < 0.35:
        return normalized_query
    if re.search(r"\b(ultimate|incredible|guide|best|easy|\d{4})\b", candidate, flags=re.I):
        return normalized_query
    return candidate


def build_row(
    query: str,
    search_query: str,
    source: str,
    results: List[Dict[str, str]],
    use_openai: bool,
    openai_model: str,
    settings,
    logger: logging.Logger,
) -> Dict[str, str]:
    picked: Optional[Dict[str, object]] = None
    if use_openai:
        picked = pick_with_openai(
            query=query,
            results=results,
            model=openai_model,
            settings=settings,
            logger=logger,
        )

    if not picked:
        picked = fallback_pick(query, results)

    recipe_name = choose_focus_keyword(query, str(picked.get("recipe_name") or ""))
    recipe_url = normalize_url(str(picked.get("recipe_url") or ""))
    raw_keywords = picked.get("keywords") if isinstance(picked, dict) else []
    keywords: List[str] = []
    if isinstance(raw_keywords, list):
        for value in raw_keywords:
            if isinstance(value, str) and value.strip():
                keywords.append(value.strip().lower())
    if not keywords:
        keywords = extract_keywords(recipe_name or query)

    return {
        "recipe": recipe_name,
        "keywords": ", ".join(keywords),
        "pinterest_url": "",
        "visit_site_url": recipe_url,
        "research_source": source,
        "search_query": search_query,
    }


def output_rows(rows: List[Dict[str, str]], fmt: str, include_header: bool) -> None:
    if fmt == "json":
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return

    fieldnames = [
        "recipe",
        "keywords",
        "pinterest_url",
        "visit_site_url",
        "research_source",
        "search_query",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    if include_header:
        writer.writeheader()
    writer.writerows(rows)
    sys.stdout.write(output.getvalue())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research keywords and extract recipe name + URL rows.",
    )
    parser.add_argument("--file", help="Path to keywords text file")
    parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Keyword to research (repeatable)",
    )
    parser.add_argument(
        "--context",
        default="",
        help="Optional context phrase appended to each keyword query (e.g. 'for dogs').",
    )
    parser.add_argument(
        "--split-commas",
        action="store_true",
        help="Split each input line by commas (off by default to preserve phrases with commas).",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--include-header",
        action="store_true",
        help="Include CSV header when using --format csv",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=6,
        help="Maximum search results to inspect per keyword (default: 6)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds (default: 20)",
    )
    parser.add_argument(
        "--openai",
        action="store_true",
        help="Use OpenAI to choose the best result and clean recipe naming",
    )
    parser.add_argument(
        "--openai-model",
        default="gpt-5-mini",
        help="OpenAI model to use (default: gpt-5-mini)",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        help="Log level (default: WARNING)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logger = setup_logger(args.log_level)

    model = (args.openai_model or "").strip()
    if model in {"", "gpt-3.5-turbo", "gpt-5-mini"}:
        model = os.getenv("OPENAI_MODEL") or os.getenv("MODEL_NAME") or model or "gpt-5-mini"

    try:
        settings = load_settings()
    except Exception as exc:
        logger.error("Failed to load settings: %s", exc)
        return 1

    keywords = read_keywords(args.file or "", args.keyword or [], split_commas=bool(args.split_commas))
    if not keywords:
        output_rows([], args.format, args.include_header)
        return 0

    pet_mode = detect_pet_mode(keywords)
    rows: List[Dict[str, str]] = []
    max_results = max(1, min(args.max_results, 12))
    timeout = max(3.0, min(args.timeout, 90.0))

    for keyword in keywords:
        search_query = build_search_query(
            keyword=keyword,
            context_hint=args.context or "",
            pet_mode=pet_mode,
        )
        if not search_query:
            continue
        source, results = search_keyword(
            search_query=search_query,
            settings=settings,
            timeout=timeout,
            max_results=max_results,
            logger=logger,
        )
        results = enrich_results_with_page_signals(
            results=results,
            query=keyword,
            timeout=timeout,
            pet_mode=pet_mode,
            logger=logger,
        )
        source_name = source
        if any(bool(item.get("has_recipe_schema")) for item in results[:3]):
            source_name = f"{source}+schema"
        row = build_row(
            query=keyword,
            search_query=search_query,
            source=source_name,
            results=results,
            use_openai=bool(args.openai),
            openai_model=model,
            settings=settings,
            logger=logger,
        )
        rows.append(row)

    output_rows(rows, args.format, args.include_header)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
