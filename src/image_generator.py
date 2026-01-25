import base64
import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

import requests
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import Settings

IMAGE_API_URL = "https://api.openai.com/v1/images/generations"


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "recipe"


def _extract_seed(prompt: str) -> str:
    match = re.search(r"--seed\s+(\d+)", prompt)
    return match.group(1) if match else "0"


def _choose_size(prompt: str) -> str:
    if "--ar 3:2" in prompt:
        return "1536x1024"
    if "--ar 2:3" in prompt:
        return "1024x1536"
    return "1024x1024"


def _request_with_retry(settings: Settings, payload: dict) -> dict:
    retryer = Retrying(
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    for attempt in retryer:
        with attempt:
            response = requests.post(
                IMAGE_API_URL,
                headers=headers,
                json=payload,
                timeout=settings.request_timeout,
            )
            if response.status_code >= 500:
                raise requests.RequestException(
                    f"Server error: {response.status_code}"
                )
            response.raise_for_status()
            return response.json()
    return {}


def _post_image_request(settings: Settings, payload: dict) -> tuple[dict, str]:
    try:
        response = requests.post(
            IMAGE_API_URL,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=settings.request_timeout,
        )
    except requests.RequestException as exc:
        return {}, str(exc)
    if response.status_code >= 400:
        return {}, response.text
    return response.json(), ""


def _save_base64_image(data: str, output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        handle.write(base64.b64decode(data))
    return str(output_path)


def _upload_to_cloudinary(
    file_path: str, focus_keyword: str, image_type: str, settings: Settings, logger: logging.Logger
) -> Optional[str]:
    if not settings.cloudinary_url:
        return None
    parsed = urlparse(settings.cloudinary_url)
    if parsed.scheme != "cloudinary":
        logger.warning("CLOUDINARY_URL scheme invalid; skipping upload")
        return None
    if "@" not in parsed.netloc:
        logger.warning("CLOUDINARY_URL missing credentials; skipping upload")
        return None

    creds, cloud_name = parsed.netloc.split("@", 1)
    api_key = None
    api_secret = None
    if ":" in creds:
        api_key, api_secret = creds.split(":", 1)

    upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
    public_id = f"{_slugify(focus_keyword)}-{image_type}-{int(time.time())}"
    folder = settings.cloudinary_folder

    data = {}
    if settings.cloudinary_upload_preset:
        data = {
            "upload_preset": settings.cloudinary_upload_preset,
            "folder": folder,
            "public_id": public_id,
        }
    elif api_key and api_secret:
        timestamp = int(time.time())
        params = {
            "folder": folder,
            "public_id": public_id,
            "timestamp": timestamp,
        }
        signature_payload = "&".join(
            [f"{key}={params[key]}" for key in sorted(params)]
        )
        signature = hashlib.sha1(
            f"{signature_payload}{api_secret}".encode("utf-8")
        ).hexdigest()
        data = {
            **params,
            "api_key": api_key,
            "signature": signature,
        }
    else:
        logger.warning("Cloudinary credentials incomplete; skipping upload")
        return None

    with open(file_path, "rb") as handle:
        files = {"file": handle}
        try:
            response = requests.post(
                upload_url,
                data=data,
                files=files,
                timeout=settings.request_timeout,
            )
        except requests.RequestException as exc:
            logger.warning("Cloudinary upload failed: %s", exc)
            return None

    if response.status_code >= 400:
        logger.warning("Cloudinary upload status %s", response.status_code)
        return None

    payload = response.json()
    return payload.get("secure_url") or payload.get("url")


def generate_image_url(
    prompt: str,
    image_type: str,
    focus_keyword: str,
    settings: Settings,
    logger: logging.Logger,
) -> str:
    if not settings.openai_api_key or not settings.generate_images:
        return ""

    size = _choose_size(prompt)
    # Always prioritize high quality for professional recipe articles
    quality_candidates = []
    if settings.image_quality:
        quality_candidates.append(settings.image_quality)
    # Ensure high quality is always tried first for professional results
    if "high" not in quality_candidates and "hd" not in quality_candidates:
        quality_candidates.insert(0, "high")
    for candidate in ["hd", "standard"]:
        if candidate not in quality_candidates:
            quality_candidates.append(candidate)
    # Only fall back to empty quality as last resort
    quality_candidates.append("")

    response = {}
    last_error = ""
    for quality in quality_candidates:
        payload = {
            "model": settings.image_model,
            "prompt": prompt,
            "size": size,
            "n": 1,
            "style": "natural",  # Professional natural style for recipe articles
        }
        if quality:
            payload["quality"] = quality

        response, error_text = _post_image_request(settings, payload)
        if response:
            last_error = ""
            break
        last_error = error_text

    if not response:
        logger.warning("Image generation failed: %s", last_error)
        return ""

    data = (response.get("data") or [{}])[0]
    b64_data = data.get("b64_json")
    url_data = data.get("url")
    if not b64_data and not url_data:
        logger.warning("Image generation returned no image data")
        return ""

    seed = _extract_seed(prompt)
    output_dir = Path(settings.image_output_dir) / _slugify(focus_keyword)
    filename = f"{image_type}_{seed}.png"
    local_path = ""
    if b64_data:
        local_path = _save_base64_image(b64_data, output_dir / filename)
    else:
        try:
            response = requests.get(url_data, timeout=settings.request_timeout)
            response.raise_for_status()
            output_dir.mkdir(parents=True, exist_ok=True)
            local_path = str(output_dir / filename)
            with open(local_path, "wb") as handle:
                handle.write(response.content)
        except requests.RequestException as exc:
            logger.warning("Failed to download generated image URL: %s", exc)
            return url_data

    uploaded_url = _upload_to_cloudinary(
        local_path, focus_keyword, image_type, settings, logger
    )
    return uploaded_url or local_path or url_data


def generate_prompt_images(
    prompts: Dict[str, str],
    focus_keyword: str,
    settings: Settings,
    logger: logging.Logger,
) -> Dict[str, str]:
    results = {}
    for key, prompt in prompts.items():
        if not prompt:
            results[key] = ""
            continue
        results[key] = generate_image_url(prompt, key, focus_keyword, settings, logger)
    return results
