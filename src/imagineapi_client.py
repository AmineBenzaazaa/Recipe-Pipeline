import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urljoin

import requests
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import Settings
from .midjourney_prompt_sanitizer import sanitize_midjourney_prompt


def _normalize_base_url(value: str) -> str:
    return value.strip().rstrip("/") if value else ""


def _headers(settings: Settings) -> Dict[str, str]:
    token = (settings.imagine_api_token or "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _looks_like_docker_api_mismatch(message: str) -> bool:
    text = (message or "").lower()
    return (
        "requested api version" in text
        or "api route and version" in text
        or "server supports the requested api version" in text
    )


def _request_with_retry(
    settings: Settings,
    method: str,
    url: str,
    **kwargs,
) -> Optional[requests.Response]:
    retryer = Retrying(
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    for attempt in retryer:
        with attempt:
            response = requests.request(
                method,
                url,
                timeout=settings.request_timeout,
                **kwargs,
            )
            if response.status_code >= 500:
                raise requests.RequestException(
                    f"Server error: {response.status_code}"
                )
            return response
    return None


def _check_imagineapi_health(base_url: str, settings: Settings, logger: logging.Logger) -> bool:
    if not base_url:
        return False
    base_url = _normalize_base_url(base_url)
    candidates = [
        f"{base_url}/server/ping",
        f"{base_url}/server/health",
        f"{base_url}/server/info",
    ]
    for url in candidates:
        try:
            response = requests.get(url, timeout=settings.request_timeout)
            if response.status_code < 400:
                return True
        except requests.RequestException:
            continue

    if settings.imagine_api_token:
        try:
            response = requests.get(
                f"{base_url}/items/images",
                params={"limit": 1, "fields": "id"},
                headers=_headers(settings),
                timeout=settings.request_timeout,
            )
            if response.status_code < 400:
                return True
        except requests.RequestException:
            pass

    return False


def _start_imagineapi_stack(settings: Settings, logger: logging.Logger) -> bool:
    repo_root = Path(__file__).resolve().parents[1]
    compose_dir = repo_root / "midjourney_engine"
    compose_file = compose_dir / "docker-compose.yml"
    if not compose_file.exists():
        logger.warning("ImagineAPI docker-compose.yml not found at %s", compose_file)
        return False

    env = os.environ.copy()
    env["PATH"] = env.get("PATH", "") + ":/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"

    docker_compose_cmd = None
    if shutil.which("docker"):
        docker_compose_cmd = ["docker", "compose"]
    elif shutil.which("docker-compose"):
        docker_compose_cmd = ["docker-compose"]
    else:
        logger.warning("Docker not found; cannot auto-start ImagineAPI")
        return False

    cmd = docker_compose_cmd + ["-f", str(compose_file), "up", "-d"]
    logger.info("Starting ImagineAPI stack: %s", " ".join(cmd))

    def _run_with(run_env: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=compose_dir,
            capture_output=True,
            text=True,
            env=run_env,
        )

    run = _run_with(env)
    if run.returncode == 0:
        return True

    message = (run.stderr or run.stdout or "").strip()

    # Docker Desktop occasionally fails API negotiation on newer clients.
    # Retry with compatible API versions before giving up.
    if _looks_like_docker_api_mismatch(message) and not env.get("DOCKER_API_VERSION"):
        for api_version in ["1.45", "1.44", "1.43", "1.42"]:
            retry_env = env.copy()
            retry_env["DOCKER_API_VERSION"] = api_version
            logger.info(
                "ImagineAPI auto-start retry with DOCKER_API_VERSION=%s",
                api_version,
            )
            run = _run_with(retry_env)
            if run.returncode == 0:
                return True
            message = (run.stderr or run.stdout or "").strip()

    logger.warning("ImagineAPI auto-start failed: %s", message or "unknown error")
    return False


def ensure_imagineapi_ready(settings: Settings, logger: logging.Logger) -> bool:
    base_url = _normalize_base_url(settings.imagine_api_url)
    if not base_url:
        logger.warning("ImagineAPI URL not configured; skipping image generation")
        return False
    if _check_imagineapi_health(base_url, settings, logger):
        return True
    logger.warning("ImagineAPI health check failed at %s", base_url)
    if not settings.imagine_api_auto_start:
        logger.warning(
            "ImagineAPI auto-start disabled. Set IMAGINE_API_AUTO_START=true or "
            "start the stack with: docker compose -f midjourney_engine/docker-compose.yml up -d"
        )
        return False

    if not _start_imagineapi_stack(settings, logger):
        return False

    deadline = time.time() + max(30, settings.imagine_api_startup_timeout_seconds)
    while time.time() < deadline:
        if _check_imagineapi_health(base_url, settings, logger):
            logger.info("ImagineAPI is healthy at %s", base_url)
            return True
        time.sleep(settings.imagine_api_poll_seconds)

    logger.warning("ImagineAPI did not become healthy within startup timeout")
    return False


def _create_image(
    prompt: str,
    settings: Settings,
    logger: logging.Logger,
) -> Optional[str]:
    base_url = _normalize_base_url(settings.imagine_api_url)
    if not base_url:
        logger.warning("ImagineAPI URL not configured; skipping image generation")
        return None
    if not settings.imagine_api_token:
        logger.warning("ImagineAPI token not configured; skipping image generation")
        return None

    payload = {"prompt": prompt}
    url = f"{base_url}/items/images"
    try:
        response = _request_with_retry(
            settings,
            "POST",
            url,
            json=payload,
            headers={
                **_headers(settings),
                "Content-Type": "application/json",
            },
        )
    except requests.RequestException as exc:
        logger.warning("ImagineAPI create failed: %s", exc)
        return None

    if response is None:
        logger.warning("ImagineAPI create failed: no response")
        return None
    if response.status_code >= 400:
        logger.warning(
            "ImagineAPI create error %s: %s",
            response.status_code,
            (response.text or "").strip(),
        )
        return None

    data = (response.json() or {}).get("data") or {}
    image_id = data.get("id")
    if not image_id:
        logger.warning("ImagineAPI create returned no image id")
        return None
    return str(image_id)


def _fetch_image_status(
    image_id: str,
    settings: Settings,
    logger: logging.Logger,
) -> Optional[dict]:
    base_url = _normalize_base_url(settings.imagine_api_url)
    url = f"{base_url}/items/images/{image_id}"
    try:
        response = _request_with_retry(
            settings,
            "GET",
            url,
            params={"fields": "status,url,upscaled_urls,discord_image_url,error"},
            headers=_headers(settings),
        )
    except requests.RequestException as exc:
        logger.warning("ImagineAPI status check failed: %s", exc)
        return None
    if response is None or response.status_code >= 400:
        return None
    return (response.json() or {}).get("data")


def _ensure_absolute_url(value: str, base_url: str) -> str:
    if not value:
        return ""
    cleaned = value.strip()
    if not cleaned:
        return ""
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned
    if not base_url:
        return ""
    base = _normalize_base_url(base_url) + "/"
    return urljoin(base, cleaned.lstrip("/"))


def _collect_image_candidates(payload: Optional[dict], base_url: str) -> list[str]:
    if not payload:
        return []
    candidates: list[str] = []
    discord_url = payload.get("discord_image_url")
    if isinstance(discord_url, str):
        candidate = _ensure_absolute_url(discord_url, base_url)
        if candidate:
            candidates.append(candidate)
    upscaled = payload.get("upscaled_urls")
    if isinstance(upscaled, list):
        for item in upscaled:
            if isinstance(item, str):
                candidate = _ensure_absolute_url(item, base_url)
                if candidate:
                    candidates.append(candidate)
    url = payload.get("url")
    if isinstance(url, str):
        candidate = _ensure_absolute_url(url, base_url)
        if candidate:
            candidates.append(candidate)
    # De-dupe while preserving order.
    seen = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered


def _pick_image_url(payload: Optional[dict], base_url: str) -> str:
    candidates = _collect_image_candidates(payload, base_url)
    return candidates[0] if candidates else ""


def generate_imagineapi_images(
    prompts: Dict[str, str],
    settings: Settings,
    logger: logging.Logger,
) -> Dict[str, str]:
    ordered_keys = ["featured", "instructions_process", "serving", "wprm_recipecard"]
    results = {key: "" for key in ordered_keys}

    if not ensure_imagineapi_ready(settings, logger):
        return results

    base_url = _normalize_base_url(settings.imagine_api_url)
    remaining_keys = [key for key in prompts.keys() if key not in ordered_keys]
    for key in ordered_keys + remaining_keys:
        prompt = (prompts.get(key) or "").strip()
        if not prompt:
            continue
        prompt = sanitize_midjourney_prompt(prompt, key)

        image_id = _create_image(prompt, settings, logger)
        if not image_id:
            continue

        fallback_url = ""
        deadline = time.time() + max(30, settings.imagine_api_timeout_seconds)
        while time.time() < deadline:
            payload = _fetch_image_status(image_id, settings, logger)
            if payload:
                discord_url = payload.get("discord_image_url")
                if isinstance(discord_url, str):
                    candidate = _ensure_absolute_url(discord_url, base_url)
                    if candidate:
                        fallback_url = candidate
                status = str(payload.get("status") or "").lower()
                if status == "completed":
                    candidates = _collect_image_candidates(payload, base_url)
                    selected_url = ""
                    if candidates:
                        if settings.image_realism_scoring and len(candidates) > 1:
                            try:
                                from .image_scoring import pick_most_realistic_image

                                selected_url = pick_most_realistic_image(
                                    candidates, settings, logger
                                )
                            except Exception as exc:
                                logger.warning(
                                    "Realism scoring failed; using first candidate: %s",
                                    exc,
                                )
                                selected_url = candidates[0]
                        else:
                            selected_url = candidates[0]
                    if not selected_url and fallback_url:
                        selected_url = fallback_url
                    results[key] = selected_url
                    break
                if status == "failed":
                    logger.warning(
                        "ImagineAPI image failed for %s: %s",
                        key,
                        payload.get("error") or "unknown error",
                    )
                    if fallback_url:
                        results[key] = fallback_url
                    break
            time.sleep(settings.imagine_api_poll_seconds)
        else:
            logger.warning("ImagineAPI timed out for %s image", key)
            if fallback_url:
                results[key] = fallback_url

    return results
