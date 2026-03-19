import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import Settings


def _clean_url(url: str) -> str:
    return url.strip().split(" ")[0]


def _extract_jsonld_images(html: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    images: List[str] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        raw = raw.strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        images.extend(_find_image_urls(data))
    return images


def _find_image_urls(node: Any) -> List[str]:
    urls: List[str] = []
    if isinstance(node, dict):
        image = node.get("image")
        if image:
            urls.extend(_normalize_to_list(image))
        if "@graph" in node:
            for item in node.get("@graph", []):
                urls.extend(_find_image_urls(item))
    elif isinstance(node, list):
        for item in node:
            urls.extend(_find_image_urls(item))
    return urls


def _normalize_to_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        results: List[str] = []
        for item in value:
            if isinstance(item, str):
                results.append(item)
            elif isinstance(item, dict) and "url" in item:
                results.append(item["url"])
        return results
    if isinstance(value, dict):
        if "url" in value:
            return [value["url"]]
        if "@list" in value:
            return [str(v) for v in value.get("@list", [])]
    if isinstance(value, str):
        return [value]
    return []


def _is_valid_image_url(url: str) -> bool:
    lowered = url.lower()
    if any(token in lowered for token in ["sprite", "icon", "logo", "avatar", "placeholder"]):
        return False
    if lowered.endswith(".svg"):
        return False
    return True


def _parse_dimension(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _resolve_image_url(url: str, base_url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = _clean_url(url)
    if base_url and not url.startswith("http"):
        url = urljoin(base_url, url)
    if not _is_valid_image_url(url):
        return None
    return url


def extract_primary_image_url(
    html: str,
    base_url: Optional[str] = None,
    recipe_image_urls: Optional[List[str]] = None,
) -> Optional[str]:
    if recipe_image_urls:
        for url in recipe_image_urls:
            resolved = _resolve_image_url(url, base_url)
            if resolved:
                return resolved

    soup = BeautifulSoup(html, "lxml")

    meta_candidates = [
        ("property", "og:image"),
        ("property", "og:image:url"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
    ]
    for attr, value in meta_candidates:
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content"):
            resolved = _resolve_image_url(tag["content"], base_url)
            if resolved:
                return resolved

    for url in _extract_jsonld_images(html):
        resolved = _resolve_image_url(url, base_url)
        if resolved:
            return resolved

    img_candidates: List[Tuple[int, str]] = []
    for img in soup.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
        )
        if not src:
            continue
        resolved = _resolve_image_url(src, base_url)
        if not resolved:
            continue
        width = _parse_dimension(img.get("width") or img.get("data-width"))
        height = _parse_dimension(img.get("height") or img.get("data-height"))
        if width and height and width * height < 40000:
            continue
        area = (width or 0) * (height or 0)
        img_candidates.append((area, resolved))

    if img_candidates:
        img_candidates.sort(key=lambda x: x[0], reverse=True)
        return img_candidates[0][1]

    return None


def extract_image_urls(
    html: str,
    base_url: Optional[str] = None,
    recipe_image_urls: Optional[List[str]] = None,
) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    urls: List[str] = []

    if recipe_image_urls:
        urls.extend(recipe_image_urls)

    urls.extend(_extract_jsonld_images(html))

    meta_candidates = [
        ("property", "og:image"),
        ("property", "og:image:url"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
    ]
    for attr, value in meta_candidates:
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content"):
            urls.append(tag["content"])

    img_candidates: List[Tuple[str, int]] = []
    for img in soup.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
        )
        if not src:
            continue
        src = _clean_url(src)
        if not _is_valid_image_url(src):
            continue
        width = _parse_dimension(img.get("width") or img.get("data-width"))
        height = _parse_dimension(img.get("height") or img.get("data-height"))
        if width and height and width * height < 40000:
            continue
        area = (width or 0) * (height or 0)
        img_candidates.append((src, area))

    img_candidates.sort(key=lambda x: x[1], reverse=True)
    for src, _area in img_candidates[:5]:
        urls.append(src)

    cleaned: List[str] = []
    seen = set()
    for url in urls:
        if not url:
            continue
        url = _clean_url(url)
        if base_url and not url.startswith("http"):
            url = urljoin(base_url, url)
        if url in seen:
            continue
        if not _is_valid_image_url(url):
            continue
        cleaned.append(url)
        seen.add(url)

    return cleaned


def download_images(
    urls: List[str],
    output_dir: str,
    settings: Settings,
    logger: logging.Logger,
    limit: int = 3,
    referer: str | None = None,
) -> List[str]:
    paths: List[str] = []
    for url in urls[:limit]:
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
                    headers = {
                        "User-Agent": settings.user_agent,
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    }
                    if referer:
                        headers["Referer"] = referer
                    response = requests.get(
                        url,
                        headers=headers,
                        timeout=settings.request_timeout,
                        stream=True,
                    )
                    if response.status_code >= 500:
                        raise requests.RequestException(
                            f"Server error: {response.status_code}"
                        )
                    break
        except requests.RequestException as exc:
            logger.warning("Image download failed for %s: %s", url, exc)
            continue
        if response.status_code >= 400:
            logger.warning("Image download status %s for %s", response.status_code, url)
            continue
        ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        filename = f"image_{len(paths) + 1}{ext}"
        path = os.path.join(output_dir, filename)
        with open(path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
        paths.append(path)
    return paths
