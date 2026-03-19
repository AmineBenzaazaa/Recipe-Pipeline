#!/usr/bin/env python3
import argparse
from collections import Counter
import logging
import os
import re
import socket
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import requests
from dotenv import load_dotenv

from src.config import load_settings
from src.image_generator import _upload_to_cloudinary
from src.imagineapi_client import ensure_imagineapi_ready
from src.midjourney_prompt_sanitizer import sanitize_midjourney_prompt

REQUIRED_IMAGE_COLUMNS = [
    "featured_image_prompt",
    "featured_image_generated_url",
    "instructions_process_image_prompt",
    "instructions_process_image_generated_url",
    "serving_image_prompt",
    "serving_image_generated_url",
]


def _setup_logger(level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger("sheet_image_worker")


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def _clean_env_value(value: str) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _find_header_index(headers: List[str], target: str) -> Optional[int]:
    target_norm = _normalize_header(target)
    for idx, header in enumerate(headers):
        if (header or "").strip().lower() == target.strip().lower():
            return idx
        if _normalize_header(header) == target_norm:
            return idx
    return None


def _match_sheet_tab_title(requested_tab: str, available_titles: List[str]) -> Optional[str]:
    requested = (requested_tab or "").strip()
    if not requested:
        return None

    for title in available_titles:
        cleaned = (title or "").strip()
        if cleaned == requested:
            return cleaned

    requested_folded = requested.casefold()
    for title in available_titles:
        cleaned = (title or "").strip()
        if cleaned.casefold() == requested_folded:
            return cleaned
    return None


def _resolve_worksheet(sheet, requested_tab: str, logger: logging.Logger):
    requested = (requested_tab or "").strip()
    if not requested:
        return sheet.sheet1

    worksheets = sheet.worksheets()
    available_titles = [(worksheet.title or "").strip() for worksheet in worksheets]
    matched_title = _match_sheet_tab_title(requested, available_titles)
    if matched_title is None:
        available = ", ".join(title for title in available_titles if title) or "<none>"
        raise ValueError(
            f"Worksheet '{requested}' not found. Available tabs: {available}"
        )

    if matched_title != requested:
        logger.warning(
            "Worksheet '%s' not found with exact case; using '%s'",
            requested,
            matched_title,
        )

    for worksheet in worksheets:
        if (worksheet.title or "").strip() == matched_title:
            return worksheet

    raise RuntimeError(
        f"Matched worksheet title '{matched_title}' but could not resolve worksheet object"
    )


def _col_to_a1(col_index_zero_based: int) -> str:
    value = col_index_zero_based + 1
    chars: List[str] = []
    while value > 0:
        value, rem = divmod(value - 1, 26)
        chars.append(chr(65 + rem))
    return "".join(reversed(chars))


def _read_cell(row: List[str], col_index: int) -> str:
    if col_index < 0 or col_index >= len(row):
        return ""
    return (row[col_index] or "").strip()


def _ensure_absolute_url(url: str, base_url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned
    base = base_url.rstrip("/") + "/"
    return urljoin(base, cleaned.lstrip("/"))


def _create_imagineapi_job(
    base_url: str,
    token: str,
    prompt: str,
    timeout_seconds: float,
) -> str:
    response = requests.post(
        f"{base_url}/items/images",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"prompt": prompt},
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"ImagineAPI create failed ({response.status_code}): {(response.text or '').strip()}"
        )
    payload = (response.json() or {}).get("data") or {}
    image_id = payload.get("id")
    if not image_id:
        raise RuntimeError("ImagineAPI create returned no image id")
    return str(image_id)


def _wait_imagineapi_completion(
    *,
    base_url: str,
    token: str,
    image_id: str,
    poll_seconds: int,
    timeout_seconds: int,
    request_timeout: float,
    logger: logging.Logger,
) -> dict:
    start_time = time.time()
    deadline = start_time + timeout_seconds
    heartbeat_interval = max(30, poll_seconds * 3)
    stagnant_warning_after = max(120, poll_seconds * 12)
    last_status: Optional[str] = None
    last_progress: Optional[str] = None
    last_change_at = start_time
    last_heartbeat_at = start_time
    stagnant_warning_emitted = False
    while time.time() < deadline:
        now = time.time()
        try:
            response = requests.get(
                f"{base_url}/items/images/{image_id}",
                headers={"Authorization": f"Bearer {token}"},
                params={"fields": "status,progress,url,upscaled_urls,discord_image_url,error"},
                timeout=request_timeout,
            )
        except requests.RequestException as exc:
            logger.warning("Status poll failed for image %s: %s", image_id, exc)
            time.sleep(poll_seconds)
            continue

        if response.status_code >= 400:
            logger.warning(
                "Status poll failed (%s): %s",
                response.status_code,
                (response.text or "").strip()[:200],
            )
            time.sleep(poll_seconds)
            continue

        payload = (response.json() or {}).get("data") or {}
        status = str(payload.get("status") or "").lower()
        progress = str(payload.get("progress") or "")
        if status != last_status or progress != last_progress:
            elapsed_seconds = int(max(0, now - start_time))
            logger.info(
                "Image %s status=%s progress=%s elapsed=%ss",
                image_id,
                status or "unknown",
                progress or "-",
                elapsed_seconds,
            )
            last_status = status
            last_progress = progress
            last_change_at = now
            last_heartbeat_at = now
            stagnant_warning_emitted = False
        elif now - last_heartbeat_at >= heartbeat_interval:
            unchanged_seconds = int(max(0, now - last_change_at))
            timeout_in_seconds = int(max(0, deadline - now))
            logger.info(
                "Image %s still waiting: status=%s progress=%s unchanged=%ss timeout_in=%ss",
                image_id,
                status or "unknown",
                progress or "-",
                unchanged_seconds,
                timeout_in_seconds,
            )
            last_heartbeat_at = now

        if (
            status in {"pending", "queued"}
            and not stagnant_warning_emitted
            and now - last_change_at >= stagnant_warning_after
        ):
            logger.warning(
                "Image %s has been %s for %ss; check ImagineAPI bot and RabbitMQ worker health",
                image_id,
                status,
                int(max(0, now - last_change_at)),
            )
            stagnant_warning_emitted = True

        if status == "completed":
            return payload
        if status == "failed":
            raise RuntimeError(f"ImagineAPI failed: {payload.get('error') or 'unknown error'}")
        time.sleep(poll_seconds)

    raise TimeoutError(
        "ImagineAPI timeout for image "
        f"{image_id} after {int(max(0, time.time() - start_time))}s "
        f"(last status={last_status or 'unknown'}, progress={last_progress or '-'})"
    )


def _pick_u2_url(payload: dict, base_url: str, upscale_index: int) -> str:
    candidates: List[str] = []
    upscaled = payload.get("upscaled_urls")
    if isinstance(upscaled, list):
        for item in upscaled:
            if isinstance(item, str):
                absolute = _ensure_absolute_url(item, base_url)
                if absolute:
                    candidates.append(absolute)

    # Prefer requested upscale (U2 => index 2 -> zero-based 1)
    zero_based = max(1, upscale_index) - 1
    if zero_based < len(candidates):
        return candidates[zero_based]

    # Fallbacks
    if candidates:
        return candidates[0]

    for key in ("discord_image_url", "url"):
        value = payload.get(key)
        if isinstance(value, str):
            absolute = _ensure_absolute_url(value, base_url)
            if absolute:
                return absolute

    raise RuntimeError("No image URL candidates found in completed ImagineAPI payload")


def _download_to_temp_file(url: str, timeout_seconds: float) -> str:
    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()

    suffix = Path(urlsplit(url).path).suffix or ".png"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(response.content)
        handle.flush()
        return handle.name
    finally:
        handle.close()


def _generate_u2_cloudinary_url(
    *,
    prompt: str,
    image_type: str,
    focus_keyword: str,
    base_url: str,
    token: str,
    upscale_index: int,
    poll_seconds: int,
    timeout_seconds: int,
    request_timeout: float,
    settings,
    logger: logging.Logger,
) -> str:
    prompt = sanitize_midjourney_prompt(prompt, image_type)
    image_id = _create_imagineapi_job(base_url, token, prompt, request_timeout)
    logger.info("Created image job %s (%s)", image_id, image_type)

    payload = _wait_imagineapi_completion(
        base_url=base_url,
        token=token,
        image_id=image_id,
        poll_seconds=poll_seconds,
        timeout_seconds=timeout_seconds,
        request_timeout=request_timeout,
        logger=logger,
    )
    source_url = _pick_u2_url(payload, base_url, upscale_index)
    temp_file = _download_to_temp_file(source_url, request_timeout)
    try:
        uploaded_url = _upload_to_cloudinary(
            file_path=temp_file,
            focus_keyword=focus_keyword,
            image_type=image_type,
            settings=settings,
            logger=logger,
        )
    finally:
        try:
            os.unlink(temp_file)
        except OSError:
            pass

    if not uploaded_url:
        raise RuntimeError("Cloudinary upload failed")
    return uploaded_url


def _build_serving_prompt(serving_prompt: str, featured_image_url: str) -> str:
    prompt = (serving_prompt or "").strip()
    featured = (featured_image_url or "").strip()
    if not featured:
        return prompt
    if featured in prompt:
        return prompt
    return f"{featured} {prompt}".strip()


def _batch_update_cells(
    worksheet,
    row_index: int,
    updates: List[Tuple[int, str]],
) -> None:
    if not updates:
        return
    payload = []
    for col_index, value in updates:
        col = _col_to_a1(col_index)
        payload.append({"range": f"{col}{row_index}", "values": [[value]]})
    worksheet.batch_update(payload, value_input_option="USER_ENTERED")


def _read_worksheet_cell(worksheet, row_index: int, col_index: int) -> str:
    col = _col_to_a1(col_index)
    cell = worksheet.acell(f"{col}{row_index}")
    return ((getattr(cell, "value", "") or "")).strip()


def _default_claim_worker_id() -> str:
    env_value = _clean_env_value(os.getenv("SHEET_WORKER_ID", ""))
    if env_value:
        return env_value
    host = (socket.gethostname() or "worker").strip() or "worker"
    return f"{host}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


def _build_claim_status_value(generating_value: str, claim_worker_id: str) -> str:
    generating = (generating_value or "").strip() or "Generating"
    worker_id = (claim_worker_id or "").strip() or "worker"
    stamp_ms = int(time.time() * 1000)
    return f"{generating}|{worker_id}|{stamp_ms}"


def _try_claim_generate_row(
    *,
    worksheet,
    row_index: int,
    status_col: int,
    generating_value: str,
    claim_worker_id: str,
    claim_settle_seconds: float,
    logger: logging.Logger,
) -> Tuple[bool, str]:
    claim_value = _build_claim_status_value(generating_value, claim_worker_id)
    _batch_update_cells(worksheet, row_index, [(status_col, claim_value)])
    if claim_settle_seconds > 0:
        time.sleep(claim_settle_seconds)
    observed_value = _read_worksheet_cell(worksheet, row_index, status_col)
    if observed_value == claim_value:
        return True, claim_value
    logger.info(
        "Row %s claim not acquired (expected=%s observed=%s)",
        row_index,
        claim_value,
        observed_value or "-",
    )
    return False, observed_value


def _parse_generating_claim(
    status_value: str, generating_value: str
) -> Optional[Tuple[str, Optional[int]]]:
    raw = (status_value or "").strip()
    if not raw:
        return None

    parts = raw.split("|", 2)
    if (parts[0] or "").strip().casefold() != (generating_value or "").strip().casefold():
        return None

    owner = (parts[1] if len(parts) >= 2 else "").strip()
    ts_ms: Optional[int] = None
    if len(parts) >= 3:
        stamp = (parts[2] or "").strip()
        if stamp.isdigit():
            try:
                ts_ms = int(stamp)
            except ValueError:
                ts_ms = None
    return owner, ts_ms


def _is_stale_generating_claim(
    *,
    now_seconds: float,
    claim_timestamp_ms: Optional[int],
    stale_after_seconds: int,
) -> bool:
    if stale_after_seconds <= 0:
        return False
    if claim_timestamp_ms is None:
        # Legacy/plain "Generating" values without metadata are treated as stale.
        return True
    age_seconds = max(0.0, now_seconds - (claim_timestamp_ms / 1000.0))
    return age_seconds >= float(stale_after_seconds)


def _extract_focus_keyword(headers: List[str], row: List[str], row_index: int) -> str:
    fallback = f"sheet-row-{row_index}"
    for candidate in ("focus_keyword", "Recipe Name", "recipe_name", "topic", "name"):
        idx = _find_header_index(headers, candidate)
        if idx is None:
            continue
        value = _read_cell(row, idx)
        if value:
            return value
    return fallback


def _resolve_column_indices(
    *,
    headers: List[str],
    status_column_name: str,
    logger: logging.Logger,
) -> Tuple[Dict[str, int], List[str], str]:
    col_indices: Dict[str, int] = {}
    missing: List[str] = []

    status_idx = _find_header_index(headers, status_column_name)
    status_used = status_column_name
    if status_idx is None:
        for candidate in ("Ready", "status"):
            status_idx = _find_header_index(headers, candidate)
            if status_idx is not None:
                logger.warning(
                    "Status column '%s' not found; using '%s' instead",
                    status_column_name,
                    candidate,
                )
                status_used = candidate
                break
    if status_idx is None:
        missing.append(status_column_name)
    else:
        col_indices["status"] = status_idx

    for header in REQUIRED_IMAGE_COLUMNS:
        idx = _find_header_index(headers, header)
        if idx is None:
            missing.append(header)
        else:
            col_indices[header] = idx

    return col_indices, missing, status_used


def _discover_target_worksheets(
    *,
    sheet,
    all_tabs: bool,
    requested_tab: str,
    logger: logging.Logger,
) -> List:
    if all_tabs:
        return list(sheet.worksheets())
    return [_resolve_worksheet(sheet, requested_tab, logger)]


def _process_generate_rows(
    *,
    worksheet,
    headers: List[str],
    status_col: int,
    featured_prompt_col: int,
    featured_url_col: int,
    instructions_prompt_col: int,
    instructions_url_col: int,
    serving_prompt_col: int,
    serving_url_col: int,
    generate_value: str,
    generating_value: str,
    ready_value: str,
    settings,
    upscale_index: int,
    timeout_seconds: int,
    logger: logging.Logger,
    max_rows: int,
    enable_row_claim: bool,
    claim_worker_id: str,
    claim_settle_seconds: float,
    generating_stale_seconds: int,
) -> Tuple[int, int]:
    values = worksheet.get_all_values()
    data_rows = values[1:] if values else []

    status_counts: Counter[str] = Counter()
    matched = 0
    completed = 0
    for row_index, row in enumerate(data_rows, start=2):
        status_value = _read_cell(row, status_col)
        status_counts[status_value or "<empty>"] += 1

        is_generate = status_value.casefold() == generate_value.casefold()
        if not is_generate and enable_row_claim:
            parsed_claim = _parse_generating_claim(status_value, generating_value)
            if parsed_claim is not None:
                owner, stamp_ms = parsed_claim
                if _is_stale_generating_claim(
                    now_seconds=time.time(),
                    claim_timestamp_ms=stamp_ms,
                    stale_after_seconds=generating_stale_seconds,
                ):
                    claim_age = (
                        "unknown"
                        if stamp_ms is None
                        else str(max(0, int(time.time() - (stamp_ms / 1000.0))))
                    )
                    logger.warning(
                        "Row %s reclaiming stale %s claim (owner=%s age=%ss)",
                        row_index,
                        generating_value,
                        owner or "-",
                        claim_age,
                    )
                    try:
                        _batch_update_cells(worksheet, row_index, [(status_col, generate_value)])
                        status_value = generate_value
                        is_generate = True
                    except Exception as reclaim_exc:
                        logger.warning(
                            "Row %s failed to reclaim stale generating status: %s",
                            row_index,
                            reclaim_exc,
                        )
                        continue

        if not is_generate:
            continue
        matched += 1
        logger.info("Processing row %s (status=%s)", row_index, status_value)

        focus_keyword = _extract_focus_keyword(headers, row, row_index)

        featured_prompt = _read_cell(row, featured_prompt_col)
        instructions_prompt = _read_cell(row, instructions_prompt_col)
        serving_prompt = _read_cell(row, serving_prompt_col)

        if not featured_prompt or not instructions_prompt or not serving_prompt:
            logger.warning(
                "Row %s skipped: one or more required prompt columns are empty",
                row_index,
            )
            continue

        row_claimed = False
        if enable_row_claim:
            try:
                claimed, current_status = _try_claim_generate_row(
                    worksheet=worksheet,
                    row_index=row_index,
                    status_col=status_col,
                    generating_value=generating_value,
                    claim_worker_id=claim_worker_id,
                    claim_settle_seconds=claim_settle_seconds,
                    logger=logger,
                )
            except Exception as exc:
                logger.warning("Row %s claim failed: %s", row_index, exc)
                continue

            if not claimed:
                logger.info(
                    "Row %s skipped after claim attempt (current status=%s)",
                    row_index,
                    current_status or "-",
                )
                continue
            row_claimed = True

        featured_url = _read_cell(row, featured_url_col)
        instructions_url = _read_cell(row, instructions_url_col)
        serving_url = _read_cell(row, serving_url_col)

        try:
            if not featured_url:
                featured_url = _generate_u2_cloudinary_url(
                    prompt=featured_prompt,
                    image_type="featured",
                    focus_keyword=focus_keyword,
                    base_url=settings.imagine_api_url.rstrip("/"),
                    token=settings.imagine_api_token,
                    upscale_index=upscale_index,
                    poll_seconds=settings.imagine_api_poll_seconds,
                    timeout_seconds=timeout_seconds,
                    request_timeout=settings.request_timeout,
                    settings=settings,
                    logger=logger,
                )
                _batch_update_cells(worksheet, row_index, [(featured_url_col, featured_url)])
                logger.info("Row %s featured image updated", row_index)

            if not instructions_url:
                instructions_url = _generate_u2_cloudinary_url(
                    prompt=instructions_prompt,
                    image_type="instructions-process",
                    focus_keyword=focus_keyword,
                    base_url=settings.imagine_api_url.rstrip("/"),
                    token=settings.imagine_api_token,
                    upscale_index=upscale_index,
                    poll_seconds=settings.imagine_api_poll_seconds,
                    timeout_seconds=timeout_seconds,
                    request_timeout=settings.request_timeout,
                    settings=settings,
                    logger=logger,
                )
                _batch_update_cells(worksheet, row_index, [(instructions_url_col, instructions_url)])
                logger.info("Row %s instructions image updated", row_index)

            if not serving_url:
                serving_final_prompt = _build_serving_prompt(serving_prompt, featured_url)
                serving_url = _generate_u2_cloudinary_url(
                    prompt=serving_final_prompt,
                    image_type="serving",
                    focus_keyword=focus_keyword,
                    base_url=settings.imagine_api_url.rstrip("/"),
                    token=settings.imagine_api_token,
                    upscale_index=upscale_index,
                    poll_seconds=settings.imagine_api_poll_seconds,
                    timeout_seconds=timeout_seconds,
                    request_timeout=settings.request_timeout,
                    settings=settings,
                    logger=logger,
                )
                _batch_update_cells(worksheet, row_index, [(serving_url_col, serving_url)])
                logger.info("Row %s serving image updated", row_index)

            _batch_update_cells(worksheet, row_index, [(status_col, ready_value)])
            logger.info("Row %s status updated to %s", row_index, ready_value)
            completed += 1
        except Exception as exc:
            logger.error("Row %s failed: %s", row_index, exc)
            if row_claimed:
                try:
                    _batch_update_cells(worksheet, row_index, [(status_col, generate_value)])
                    logger.info(
                        "Row %s status reset to %s after failure",
                        row_index,
                        generate_value,
                    )
                except Exception as rollback_exc:
                    logger.warning(
                        "Row %s failed to reset status after error: %s",
                        row_index,
                        rollback_exc,
                    )
            continue

        if max_rows > 0 and completed >= max_rows:
            break

    if matched == 0 and status_counts:
        summary = ", ".join(
            f"{status!r}:{count}" for status, count in status_counts.most_common(8)
        )
        logger.info(
            "No rows matched status=%r. Observed status values in selected column: %s",
            generate_value,
            summary,
        )

    return matched, completed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Autonomous Google Sheet image worker (Generate -> Ready)"
    )
    parser.add_argument(
        "--sheet-url",
        default="",
        help="Google Sheet URL (defaults to GOOGLE_SHEET_URL)",
    )
    parser.add_argument(
        "--sheet-tab",
        default="",
        help="Worksheet/tab title (defaults to GOOGLE_SHEET_TAB or Tastetorate.com; ignored with --all-tabs)",
    )
    parser.add_argument(
        "--all-tabs",
        action="store_true",
        help="Process all worksheet tabs in the spreadsheet",
    )
    parser.add_argument(
        "--sheet-credentials",
        default="",
        help="Service-account JSON path",
    )
    parser.add_argument("--status-column", default="status")
    parser.add_argument("--status-generate", default="Generate")
    parser.add_argument("--status-generating", default="Generating")
    parser.add_argument("--status-ready", default="Ready")
    parser.add_argument(
        "--upscale-index",
        type=int,
        default=2,
        help="Upscale index to select (1=U1, 2=U2, ...). Default: 2",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=0,
        help="Per-image timeout including queue wait. 0 uses max(IMAGINE_API_TIMEOUT_SECONDS, 1800)",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=30,
        help="Watch-mode sheet polling interval",
    )
    parser.add_argument(
        "--max-rows-per-pass",
        type=int,
        default=0,
        help="Optional cap per pass (0 = no cap)",
    )
    parser.add_argument(
        "--no-row-claim",
        action="store_true",
        help="Disable best-effort row claim (Generate -> Generating) for concurrent workers",
    )
    parser.add_argument(
        "--claim-worker-id",
        default="",
        help="Worker id used in Generating claim marker (defaults to SHEET_WORKER_ID or hostname/pid)",
    )
    parser.add_argument(
        "--claim-settle-seconds",
        type=float,
        default=0.8,
        help="Delay before claim verification read-back",
    )
    parser.add_argument(
        "--generating-stale-seconds",
        type=int,
        default=0,
        help="Reclaim Generating rows older than this many seconds (0 = auto based on timeout)",
    )
    parser.add_argument("--watch", action="store_true", help="Run continuously")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    load_dotenv(dotenv_path=".env")
    if not args.sheet_url:
        args.sheet_url = _clean_env_value(os.getenv("GOOGLE_SHEET_URL", ""))
    if not args.sheet_tab and not args.all_tabs:
        args.sheet_tab = _clean_env_value(os.getenv("GOOGLE_SHEET_TAB", "")) or "Tastetorate.com"
    args.sheet_tab = (args.sheet_tab or "").strip()
    if not args.sheet_credentials:
        args.sheet_credentials = _clean_env_value(
            os.getenv(
                "GOOGLE_SHEET_CREDENTIALS",
                str(Path(".secrets") / "google-service-account.json"),
            )
        )

    logger = _setup_logger(args.log_level)
    settings = load_settings()
    args.claim_settle_seconds = max(0.0, args.claim_settle_seconds)
    row_claim_enabled = not args.no_row_claim
    claim_worker_id = (args.claim_worker_id or "").strip() or _default_claim_worker_id()
    if args.timeout_seconds <= 0:
        args.timeout_seconds = max(settings.imagine_api_timeout_seconds, 1800)
    if args.generating_stale_seconds <= 0:
        # Each row can process up to 3 image generations. Keep stale reclaim beyond expected row runtime.
        args.generating_stale_seconds = max(3600, (args.timeout_seconds * 3) + 300)
    else:
        args.generating_stale_seconds = max(0, args.generating_stale_seconds)

    if not args.sheet_url:
        logger.error("Missing --sheet-url (or GOOGLE_SHEET_URL)")
        return 1
    if not args.sheet_credentials:
        logger.error("Missing --sheet-credentials (or GOOGLE_SHEET_CREDENTIALS)")
        return 1
    if not Path(args.sheet_credentials).exists():
        logger.error("Sheet credentials file not found: %s", args.sheet_credentials)
        return 1
    if not settings.imagine_api_url or not settings.imagine_api_token:
        logger.error("ImagineAPI is not configured (IMAGINE_API_URL / IMAGINE_API_TOKEN)")
        return 1
    if not settings.cloudinary_url:
        logger.error("Cloudinary is not configured (CLOUDINARY_URL)")
        return 1

    if not ensure_imagineapi_ready(settings, logger):
        if args.watch:
            logger.warning(
                "ImagineAPI is not ready at startup; entering watch retry loop"
            )
        else:
            logger.error("ImagineAPI is not ready")
            return 1

    import gspread

    client = gspread.service_account(filename=args.sheet_credentials)
    sheet = client.open_by_url(args.sheet_url)
    if args.all_tabs:
        logger.info(
            "Worker started for all tabs (Generate='%s' -> Generating='%s' -> Ready='%s', claim=%s worker=%s, U%s)",
            args.status_generate,
            args.status_generating,
            args.status_ready,
            "on" if row_claim_enabled else "off",
            claim_worker_id if row_claim_enabled else "-",
            args.upscale_index,
        )
    else:
        try:
            worksheet = _resolve_worksheet(sheet, args.sheet_tab, logger)
        except Exception as exc:
            logger.error("%s", exc)
            return 1
        logger.info(
            "Worker started for tab '%s' (Generate='%s' -> Generating='%s' -> Ready='%s', claim=%s worker=%s, U%s)",
            worksheet.title,
            args.status_generate,
            args.status_generating,
            args.status_ready,
            "on" if row_claim_enabled else "off",
            claim_worker_id if row_claim_enabled else "-",
            args.upscale_index,
        )

    while True:
        if args.watch and not ensure_imagineapi_ready(settings, logger):
            wait_seconds = max(5, args.poll_seconds)
            logger.error("ImagineAPI is not ready; retrying in %ss", wait_seconds)
            time.sleep(wait_seconds)
            continue

        try:
            worksheets = _discover_target_worksheets(
                sheet=sheet,
                all_tabs=args.all_tabs,
                requested_tab=args.sheet_tab,
                logger=logger,
            )

            if not worksheets:
                raise RuntimeError("No worksheet tabs found")

            pass_tab_count = 0
            pass_matched = 0
            pass_completed = 0
            for worksheet in worksheets:
                if args.max_rows_per_pass > 0 and pass_completed >= args.max_rows_per_pass:
                    break

                try:
                    headers = worksheet.row_values(1)
                except Exception as exc:
                    if args.all_tabs:
                        logger.warning(
                            "Tab '%s' skipped: unable to read headers (%s)",
                            worksheet.title,
                            exc,
                        )
                        continue
                    raise

                if not headers:
                    if args.all_tabs:
                        logger.warning("Tab '%s' skipped: no headers in row 1", worksheet.title)
                        continue
                    logger.error("Sheet has no headers in row 1")
                    return 1

                col_indices, missing, status_used = _resolve_column_indices(
                    headers=headers,
                    status_column_name=args.status_column,
                    logger=logger,
                )
                if missing:
                    missing_text = ", ".join(missing)
                    if args.all_tabs:
                        logger.warning(
                            "Tab '%s' skipped: missing required columns: %s",
                            worksheet.title,
                            missing_text,
                        )
                        continue
                    logger.error("Missing required sheet columns: %s", missing_text)
                    return 1

                per_tab_limit = 0
                if args.max_rows_per_pass > 0:
                    per_tab_limit = max(args.max_rows_per_pass - pass_completed, 0)

                matched, completed = _process_generate_rows(
                    worksheet=worksheet,
                    headers=headers,
                    status_col=col_indices["status"],
                    featured_prompt_col=col_indices["featured_image_prompt"],
                    featured_url_col=col_indices["featured_image_generated_url"],
                    instructions_prompt_col=col_indices["instructions_process_image_prompt"],
                    instructions_url_col=col_indices["instructions_process_image_generated_url"],
                    serving_prompt_col=col_indices["serving_image_prompt"],
                    serving_url_col=col_indices["serving_image_generated_url"],
                    generate_value=args.status_generate,
                    generating_value=args.status_generating,
                    ready_value=args.status_ready,
                    settings=settings,
                    upscale_index=args.upscale_index,
                    timeout_seconds=args.timeout_seconds,
                    logger=logger,
                    max_rows=per_tab_limit,
                    enable_row_claim=row_claim_enabled,
                    claim_worker_id=claim_worker_id,
                    claim_settle_seconds=args.claim_settle_seconds,
                    generating_stale_seconds=args.generating_stale_seconds,
                )
                pass_tab_count += 1
                pass_matched += matched
                pass_completed += completed
                logger.info(
                    "Tab '%s' pass finished: matched=%s completed=%s status_col=%s",
                    worksheet.title,
                    matched,
                    completed,
                    status_used,
                )

            logger.info(
                "Pass summary: tabs=%s matched=%s completed=%s",
                pass_tab_count,
                pass_matched,
                pass_completed,
            )
        except Exception as exc:
            logger.exception("Pass failed: %s", exc)

        if not args.watch:
            break
        time.sleep(max(5, args.poll_seconds))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
