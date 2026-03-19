#!/usr/bin/env python3
"""
Mark stale ImagineAPI image jobs as failed in bulk.

By default this script performs a dry run. Use --apply to execute updates.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import load_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cleanup stale ImagineAPI image jobs by marking them failed."
    )
    parser.add_argument(
        "--status",
        action="append",
        default=["pending"],
        help="Status to include. Can be provided multiple times (default: pending).",
    )
    parser.add_argument(
        "--older-than-minutes",
        type=int,
        default=120,
        help="Only cleanup jobs older than this many minutes (default: 120).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum number of records to inspect (default: 500).",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Page size for API listing (default: 100).",
    )
    parser.add_argument(
        "--reason",
        default="Marked failed by stale-job cleanup",
        help="Reason text written to the image error field.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates. Without this flag the script runs in dry-run mode.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each candidate record as it is evaluated.",
    )
    return parser.parse_args()


def _normalize_statuses(values: Iterable[str]) -> List[str]:
    statuses: List[str] = []
    for value in values:
        cleaned = (value or "").strip().lower()
        if cleaned and cleaned not in statuses:
            statuses.append(cleaned)
    return statuses or ["pending"]


def _parse_iso8601(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _request_json(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    timeout_seconds: float,
    params: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    response = requests.request(
        method,
        url,
        headers=headers,
        timeout=timeout_seconds,
        params=params,
        json=json_body,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"{method} {url} failed ({response.status_code}): {(response.text or '').strip()}"
        )
    return response.json() if response.content else {}


def _fetch_images(
    *,
    base_url: str,
    token: str,
    statuses: List[str],
    timeout_seconds: float,
    limit: int,
    page_size: int,
) -> List[Dict[str, object]]:
    headers = {"Authorization": f"Bearer {token}"}
    collected: List[Dict[str, object]] = []
    page = 1
    capped_page_size = max(1, min(page_size, 200))

    while len(collected) < limit:
        remaining = limit - len(collected)
        current_page_size = min(capped_page_size, remaining)
        params: Dict[str, str] = {
            "fields": "id,status,error,progress,date_created,date_updated",
            "sort[]": "-date_created",
            "limit": str(current_page_size),
            "page": str(page),
        }
        if len(statuses) == 1:
            params["filter[status][_eq]"] = statuses[0]
        else:
            params["filter[status][_in]"] = ",".join(statuses)

        payload = _request_json(
            "GET",
            f"{base_url}/items/images",
            headers=headers,
            timeout_seconds=timeout_seconds,
            params=params,
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            break

        for row in data:
            if isinstance(row, dict):
                collected.append(row)

        page += 1

    return collected


def _format_minutes(seconds: float) -> str:
    return f"{seconds / 60:.1f}"


def main() -> int:
    args = _parse_args()
    statuses = _normalize_statuses(args.status)
    older_than_minutes = max(1, args.older_than_minutes)
    mode = "APPLY" if args.apply else "DRY-RUN"

    settings = load_settings()
    base_url = (settings.imagine_api_url or "").strip().rstrip("/")
    token = (settings.imagine_api_token or "").strip()

    if not base_url or not token:
        print("ImagineAPI is not configured (IMAGINE_API_URL / IMAGINE_API_TOKEN).")
        return 2

    now = datetime.now(timezone.utc)
    min_age_seconds = older_than_minutes * 60
    timeout_seconds = settings.request_timeout

    try:
        records = _fetch_images(
            base_url=base_url,
            token=token,
            statuses=statuses,
            timeout_seconds=timeout_seconds,
            limit=max(1, args.limit),
            page_size=max(1, args.page_size),
        )
    except Exception as exc:
        print(f"Failed to fetch image records: {exc}")
        return 1

    stale_records: List[Dict[str, object]] = []

    for row in records:
        image_id = str(row.get("id") or "").strip()
        status = str(row.get("status") or "").strip().lower()
        created_at = _parse_iso8601(str(row.get("date_created") or ""))
        updated_at = _parse_iso8601(str(row.get("date_updated") or ""))
        reference_time = updated_at or created_at
        if not image_id or not reference_time:
            continue

        age_seconds = (now - reference_time).total_seconds()
        if age_seconds < min_age_seconds:
            continue

        row["_age_seconds"] = age_seconds
        row["_status"] = status
        stale_records.append(row)

        if args.verbose:
            print(
                f"candidate id={image_id} status={status} age_minutes={_format_minutes(age_seconds)}"
            )

    print(
        f"[{mode}] scanned={len(records)} stale_candidates={len(stale_records)} "
        f"statuses={','.join(statuses)} older_than_minutes={older_than_minutes}"
    )

    if not stale_records:
        return 0

    if not args.apply:
        for row in stale_records[:30]:
            image_id = str(row.get("id") or "")
            status = str(row.get("_status") or row.get("status") or "")
            age_seconds = float(row.get("_age_seconds") or 0.0)
            print(
                f"  - id={image_id} status={status} age_minutes={_format_minutes(age_seconds)}"
            )
        if len(stale_records) > 30:
            print(f"  ... and {len(stale_records) - 30} more")
        print("Dry run complete. Re-run with --apply to update records.")
        return 0

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    updated = 0
    failed = 0

    for row in stale_records:
        image_id = str(row.get("id") or "").strip()
        if not image_id:
            continue
        previous_status = str(row.get("_status") or row.get("status") or "").strip()
        age_seconds = float(row.get("_age_seconds") or 0.0)
        reason = (
            f"{args.reason} | previous_status={previous_status or 'unknown'} "
            f"| stale_minutes={_format_minutes(age_seconds)}"
        )

        payload = {
            "status": "failed",
            "progress": None,
            "error": reason,
        }

        try:
            _request_json(
                "PATCH",
                f"{base_url}/items/images/{image_id}",
                headers=headers,
                timeout_seconds=timeout_seconds,
                json_body=payload,
            )
            updated += 1
            print(
                f"updated id={image_id} previous_status={previous_status} "
                f"stale_minutes={_format_minutes(age_seconds)}"
            )
        except Exception as exc:
            failed += 1
            print(f"failed id={image_id}: {exc}")

    print(
        f"[APPLY] done updated={updated} failed={failed} total_candidates={len(stale_records)}"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
