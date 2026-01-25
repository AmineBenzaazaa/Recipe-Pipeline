import logging
from typing import Any, Dict

import requests
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import Settings

RESPONSES_URL = "https://api.openai.com/v1/responses"


def _extract_output_text(payload: Dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    if isinstance(payload.get("output_text"), str):
        return payload.get("output_text", "")
    outputs = payload.get("output") or []
    texts = []
    for item in outputs:
        for content in item.get("content", []) or []:
            if content.get("type") in {"output_text", "text"}:
                texts.append(content.get("text", ""))
    return "".join(texts).strip()


def _request_with_retry(settings: Settings, payload: Dict[str, Any]) -> Dict[str, Any]:
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
                RESPONSES_URL,
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


def responses_create_text(
    settings: Settings,
    payload: Dict[str, Any],
    logger: logging.Logger,
) -> str:
    if not settings.openai_api_key:
        return ""

    try:
        from openai import OpenAI

        if hasattr(OpenAI, "responses"):
            client = OpenAI(api_key=settings.openai_api_key)
            response = client.responses.create(**payload)
            return getattr(response, "output_text", "") or ""
    except Exception as exc:
        logger.warning("OpenAI client failed; falling back to HTTP: %s", exc)

    try:
        data = _request_with_retry(settings, payload)
    except requests.RequestException as exc:
        logger.warning("OpenAI HTTP request failed: %s", exc)
        return ""

    return _extract_output_text(data)
