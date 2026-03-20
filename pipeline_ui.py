#!/usr/bin/env python3
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import streamlit as st
from dotenv import dotenv_values, set_key

from src.output_language import (
    DEFAULT_SITE_LANGUAGE_MAP,
    load_site_language_map_from_file,
    parse_site_language_map,
    resolve_output_language,
)
from src.sheets_client import list_sheet_worksheets


APP_DIR = Path(__file__).resolve().parent
ENV_PATH = APP_DIR / ".env"
SECRETS_DIR = APP_DIR / ".secrets"
DEFAULT_SHEET_CREDENTIALS_PATH = SECRETS_DIR / "google-service-account.json"
PIN_EXTRACT_PATH = APP_DIR / "pin_extract.py"
KEYWORD_EXTRACT_PATH = APP_DIR / "keyword_extract.py"
GENERATOR_PATH = APP_DIR / "generate_recipe_batch.py"
DEFAULT_PINS_PATH = APP_DIR / "pins.txt"
DEFAULT_KEYWORDS_PATH = APP_DIR / "keywords.txt"
DEFAULT_INPUT_PATH = APP_DIR / "batch_input.csv"
DEFAULT_OUTPUT_PATH = APP_DIR / "batch_output.csv"
DEFAULT_KEYWORD_INPUT_PATH = APP_DIR / "keywords_batch_input.csv"
DEFAULT_KEYWORD_OUTPUT_PATH = APP_DIR / "keywords_batch_output.csv"
DEFAULT_SITE_LANGUAGE_MAP_PATH = SECRETS_DIR / "site_language_map.json"
LOG_TAIL_LIMIT = 400
PAUSE_FILE = APP_DIR / ".pipeline_pause"


def load_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError:
        return ""


def format_duration(seconds: Optional[float]) -> str:
    if not seconds:
        return "--"
    seconds = max(seconds, 0.0)
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remainder = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {remainder}s"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m"


def format_timestamp(value: Optional[datetime]) -> str:
    if not value:
        return "--"
    return value.strftime("%b %d %I:%M %p")


def estimate_pin_count(text: str) -> int:
    if not text:
        return 0
    urls = extract_pinterest_pin_urls(text)
    if urls:
        return len(urls)
    return len([line.strip() for line in text.splitlines() if line.strip()])


def estimate_keyword_count(text: str) -> int:
    if not text:
        return 0
    return len([line.strip() for line in text.splitlines() if line.strip()])


def extract_pinterest_pin_urls(text: str) -> List[str]:
    if not text:
        return []

    raw_urls = re.findall(r"https?://[^\s\"'<>]+", text)
    cleaned_urls: List[str] = []
    seen = set()
    for raw in raw_urls:
        url = raw.strip().rstrip("),.;")
        lowered = url.lower()
        if "pinterest." not in lowered or "/pin/" not in lowered:
            continue
        if url in seen:
            continue
        seen.add(url)
        cleaned_urls.append(url)
    return cleaned_urls


def safe_dataframe(data: Any, *, use_container_width: bool = True, fallback_max_rows: int = 100) -> None:
    try:
        st.dataframe(data, use_container_width=use_container_width)
        return
    except Exception as exc:
        if not st.session_state.get("_dataframe_fallback_warned", False):
            st.warning(
                "Interactive table unavailable in this environment. "
                f"Showing a text preview instead. ({exc.__class__.__name__})"
            )
            st.session_state["_dataframe_fallback_warned"] = True

    preview = data
    if isinstance(data, list):
        row_count = len(data)
        preview = data[:fallback_max_rows]
        if row_count > fallback_max_rows:
            st.caption(f"Showing first {fallback_max_rows} of {row_count} rows.")

    if isinstance(preview, list) and preview and all(isinstance(row, dict) for row in preview):
        columns = list(preview[0].keys())
        markdown_rows = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join(["---"] * len(columns)) + " |",
        ]
        for row in preview:
            cells: List[str] = []
            for col in columns:
                cell = str(row.get(col, "")).replace("\n", " ").replace("|", "\\|").strip()
                if len(cell) > 160:
                    cell = f"{cell[:157]}..."
                cells.append(cell)
            markdown_rows.append("| " + " | ".join(cells) + " |")
        st.markdown("\n".join(markdown_rows))
        return

    try:
        st.code(json.dumps(preview, indent=2, ensure_ascii=False, default=str))
    except TypeError:
        st.code(str(preview))


def _extract_keyword_terms(value: str, limit: int = 8) -> List[str]:
    tokens = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9'_-]*", (value or "").lower())
    stopwords = {"a", "an", "and", "or", "the", "of", "to", "for", "with", "in", "on", "recipe"}
    deduped: List[str] = []
    seen = set()
    for token in tokens:
        normalized = token.strip("'-_")
        if not normalized or normalized in stopwords or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def build_keyword_only_rows(keywords_text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen = set()
    for line in keywords_text.splitlines():
        cleaned = (line or "").strip().strip("\"'`")
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "recipe": cleaned,
                "keywords": ", ".join(_extract_keyword_terms(cleaned)),
                "pinterest_url": "",
                "visit_site_url": "",
                "research_source": "keyword_only",
                "search_query": f"{cleaned} recipe",
            }
        )
    return rows


def run_pin_extract(
    pins_text: str,
    timeout: float,
    use_openai: bool,
    openai_model: str,
) -> List[Dict[str, str]]:
    urls = extract_pinterest_pin_urls(pins_text)
    if not urls:
        fallback_text = load_text_file(DEFAULT_PINS_PATH)
        urls = extract_pinterest_pin_urls(fallback_text)
    if not urls:
        raise ValueError(
            "No Pinterest pin URLs found in Pins input or pins.txt. "
            "Paste full pin links or choose 'Load pins.txt'."
        )

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as handle:
        handle.write("\n".join(urls))
        temp_path = Path(handle.name)

    cmd = [
        sys.executable,
        str(PIN_EXTRACT_PATH),
        "--format",
        "json",
        "--file",
        str(temp_path),
        "--timeout",
        str(timeout),
    ]
    if use_openai:
        cmd.extend(["--openai", "--openai-model", openai_model])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "pin_extract failed"
        raise RuntimeError(message)

    output = result.stdout.strip()
    if not output:
        return []
    data = json.loads(output)
    if not isinstance(data, list):
        raise ValueError("pin_extract output is not a list")
    return data


def run_keyword_extract(
    keywords_text: str,
    timeout: float,
    max_results: int,
    use_openai: bool,
    openai_model: str,
    context_hint: str = "",
) -> List[Dict[str, str]]:
    if not keywords_text.strip():
        return []

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as handle:
        handle.write(keywords_text)
        temp_path = Path(handle.name)

    cmd = [
        sys.executable,
        str(KEYWORD_EXTRACT_PATH),
        "--format",
        "json",
        "--file",
        str(temp_path),
        "--timeout",
        str(timeout),
        "--max-results",
        str(max_results),
    ]
    if context_hint.strip():
        cmd.extend(["--context", context_hint.strip()])
    if use_openai:
        cmd.extend(["--openai", "--openai-model", openai_model])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "keyword_extract failed"
        raise RuntimeError(message)

    output = result.stdout.strip()
    if not output:
        return []
    data = json.loads(output)
    if not isinstance(data, list):
        raise ValueError("keyword_extract output is not a list")
    return data


def build_batch_rows(rows: List[Dict[str, str]], drop_missing: bool) -> tuple[List[Dict[str, str]], dict]:
    """Build batch rows and return stats."""
    batch_rows = []
    stats = {
        "total": len(rows),
        "with_url": 0,
        "without_url": 0,
        "included": 0,
        "dropped": 0
    }
    
    for row in rows:
        recipe = (row.get("recipe") or "").strip()
        pinterest_url = (row.get("pinterest_url") or "").strip()
        visit_url = (row.get("visit_site_url") or "").strip()
        
        if visit_url:
            stats["with_url"] += 1
        else:
            stats["without_url"] += 1

        if drop_missing and (not recipe or not visit_url):
            stats["dropped"] += 1
            continue
        
        stats["included"] += 1
        batch_rows.append(
            {
                "Recipe Name": recipe,
                "Pinterest URL": pinterest_url,
                "Recipe URL": visit_url,
            }
        )
    return batch_rows, stats


def rows_to_csv(rows: List[Dict[str, str]], fieldnames: List[str]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def write_csv(path: Path, rows: List[Dict[str, str]], fieldnames: List[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader]


def run_generator(
    input_path: Path,
    output_path: Path,
    log_level: str,
    allow_missing_url: bool = False,
    sheet_url: str = "",
    sheet_tab: str = "",
    sheet_credentials: str = "",
    sheet_ready_value: str = "",
) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(GENERATOR_PATH),
        "--input",
        str(input_path),
        "--out",
        str(output_path),
        "--log-level",
        log_level,
    ]
    if allow_missing_url:
        cmd.append("--allow-missing-url")
    if sheet_url:
        cmd.extend(["--sheet-url", sheet_url])
    if sheet_tab:
        cmd.extend(["--sheet-tab", sheet_tab])
    if sheet_credentials:
        cmd.extend(["--sheet-credentials", sheet_credentials])
    if sheet_ready_value:
        cmd.extend(["--sheet-ready-value", sheet_ready_value])
    return subprocess.run(cmd, capture_output=True, text=True)


def run_generator_stream(
    input_path: Path,
    output_path: Path,
    log_level: str,
    log_placeholder,
    progress_placeholder,
    total_targets: int,
    allow_missing_url: bool = False,
    sheet_url: str = "",
    sheet_tab: str = "",
    sheet_credentials: str = "",
    sheet_ready_value: str = "",
    max_log_lines: int = LOG_TAIL_LIMIT,
) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(GENERATOR_PATH),
        "--input",
        str(input_path),
        "--out",
        str(output_path),
        "--log-level",
        log_level,
    ]
    if allow_missing_url:
        cmd.append("--allow-missing-url")
    if sheet_url:
        cmd.extend(["--sheet-url", sheet_url])
    if sheet_tab:
        cmd.extend(["--sheet-tab", sheet_tab])
    if sheet_credentials:
        cmd.extend(["--sheet-credentials", sheet_credentials])
    if sheet_ready_value:
        cmd.extend(["--sheet-ready-value", sheet_ready_value])

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    log_lines: List[str] = []
    processed = 0

    if process.stdout is None:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        combined = "\n".join(
            [content for content in (result.stdout.strip(), result.stderr.strip()) if content]
        )
        return result.returncode, combined

    for line in iter(process.stdout.readline, ""):
        if not line:
            if process.poll() is not None:
                break
            continue
        cleaned = line.rstrip()
        if cleaned:
            log_lines.append(cleaned)
            if len(log_lines) > max_log_lines:
                log_lines = log_lines[-max_log_lines:]
            if log_placeholder:
                log_placeholder.code("\n".join(log_lines))
            if progress_placeholder and total_targets:
                if "Processing " in cleaned:
                    processed += 1
                    ratio = min(processed / total_targets, 1.0)
                    progress_placeholder.progress(
                        ratio,
                        text=f"Processing {processed}/{total_targets}",
                    )

    returncode = process.wait()
    if progress_placeholder:
        if total_targets:
            progress_placeholder.progress(
                1.0,
                text=f"Completed {processed}/{total_targets}",
            )
        else:
            progress_placeholder.progress(1.0, text="Completed")
    return returncode, "\n".join(log_lines)


def render_progress(step_one: bool, step_two: bool, output_ready: bool, container=st) -> None:
    def dot(active: bool) -> str:
        color = "#2a6f5e" if active else "#c9b9a9"
        return f'<span class="rail-dot" style="background:{color};"></span>'

    html = f"""
    <div class="rail">
      <div class="rail-title">Pipeline Status</div>
      <div class="rail-item">{dot(step_one)} Step 1 ready</div>
      <div class="rail-item">{dot(step_two)} Step 2 prepared</div>
      <div class="rail-item">{dot(output_ready)} Final table ready</div>
      <div class="rail-note">Use the Engine panel to run the full pipeline.</div>
    </div>
    """
    container.markdown(html, unsafe_allow_html=True)


def render_run_panel(
    active_run: str,
    last_step_one: dict,
    last_step_two: dict,
    input_estimate: int,
    extracted_rows_count: int,
    batch_rows_count: int,
    step_one_timeout: float,
    input_label: str = "Pins in input",
    extracted_label: str = "Extracted pins",
    container=st,
) -> None:
    status_map = {
        "step1": ("Step 1 running", "pill-running"),
        "step2": ("Step 2 running", "pill-running"),
        "": ("Idle", "pill-idle"),
    }
    status_label, status_class = status_map.get(active_run, ("Busy", "pill-running"))

    def format_last_run(run_info: dict) -> str:
        if not run_info:
            return "Not run yet"
        completed_at = run_info.get("completed_at")
        duration = run_info.get("duration")
        status = run_info.get("status", "success")
        when = format_timestamp(completed_at)
        took = format_duration(duration)
        if status == "error":
            return f"{when} | failed | {took}"
        return f"{when} | {took}"

    step_one_text = format_last_run(last_step_one)
    step_two_text = format_last_run(last_step_two)
    estimate_seconds = input_estimate * step_one_timeout if input_estimate and step_one_timeout else 0
    estimate_text = (
        f"Upper bound for Step 1: {format_duration(estimate_seconds)}"
        if estimate_seconds
        else "Upper bound for Step 1: --"
    )

    html = f"""
    <div class="side-card">
      <div class="rail-title">Process Monitor</div>
      <div class="rail-row"><span>Current</span><span class="pill {status_class}">{status_label}</span></div>
      <div class="rail-row"><span>Step 1 last run</span><span>{step_one_text}</span></div>
      <div class="rail-row"><span>Step 2 last run</span><span>{step_two_text}</span></div>
      <div class="rail-divider"></div>
      <div class="rail-row"><span>{input_label}</span><span>{input_estimate}</span></div>
      <div class="rail-row"><span>{extracted_label}</span><span>{extracted_rows_count}</span></div>
      <div class="rail-row"><span>Batch rows</span><span>{batch_rows_count}</span></div>
      <div class="rail-note">{estimate_text}</div>
    </div>
    """
    container.markdown(html, unsafe_allow_html=True)


def render_batch_stats(stats: dict) -> None:
    if not stats:
        return
    if stats["total"] > 0:
        st.info(
            f"📊 **Batch Statistics:**\n\n"
            f"- Total pins extracted: {stats['total']}\n"
            f"- Pins with Recipe URLs: {stats['with_url']} ✅\n"
            f"- Pins without Recipe URLs: {stats['without_url']} ⚠️\n"
            f"- Included in batch: {stats['included']}\n"
            f"- Dropped: {stats['dropped']}"
        )
        if stats["without_url"] > 0:
            st.warning(
                f"⚠️ {stats['without_url']} Pinterest pins don't have external recipe URLs. "
                f"These are Pinterest-only pins and cannot be processed by the recipe generator. "
                f"Uncheck the filter above to include them in the CSV, but they will be skipped during processing."
            )


def render_keyword_batch_stats(stats: dict) -> None:
    if not stats:
        return
    if stats["total"] > 0:
        st.info(
            f"📊 **Batch Statistics:**\n\n"
            f"- Total keyword rows researched: {stats['total']}\n"
            f"- Rows with Recipe URLs: {stats['with_url']} ✅\n"
            f"- Rows without Recipe URLs: {stats['without_url']} ⚠️\n"
            f"- Included in batch: {stats['included']}\n"
            f"- Dropped: {stats['dropped']}"
        )
        if stats["without_url"] > 0:
            st.info(
                f"ℹ️ {stats['without_url']} researched keyword rows don't have recipe URLs. "
                f"That's okay in keyword-only mode; Step 2 can generate from keywords directly."
            )


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink: #1c1915;
          --muted: #5b5147;
          --panel: #fff8ed;
          --border: #e3d2bf;
          --accent: #d96b3a;
          --accent-2: #2a6f5e;
          --shadow: rgba(28, 25, 21, 0.08);
        }
        html, body, [class*="css"]  {
          font-family: "Palatino Linotype", "Book Antiqua", Palatino, serif;
          color: var(--ink);
        }
        .stApp {
          background:
            radial-gradient(900px 500px at 10% -10%, rgba(217, 107, 58, 0.16), transparent 60%),
            radial-gradient(900px 500px at 90% 10%, rgba(42, 111, 94, 0.18), transparent 60%),
            linear-gradient(180deg, #f7f1e8 0%, #efe5d9 100%);
        }
        h1, h2, h3 {
          font-family: "Palatino Linotype", "Book Antiqua", Palatino, serif;
        }
        .hero {
          padding: 18px 22px;
          border: 1px solid var(--border);
          border-radius: 18px;
          background: rgba(255, 248, 237, 0.9);
          box-shadow: 0 10px 30px var(--shadow);
          margin-bottom: 16px;
          animation: rise 0.7s ease-out;
        }
        .hero-kicker {
          letter-spacing: 0.12em;
          text-transform: uppercase;
          font-size: 0.72rem;
          color: var(--accent-2);
          font-weight: 600;
        }
        .hero-title {
          font-size: 2rem;
          margin: 6px 0 8px;
        }
        .hero-copy {
          color: var(--muted);
          margin: 0;
        }
        .section-title {
          font-size: 1.3rem;
          margin: 18px 0 8px;
          padding-bottom: 6px;
          border-bottom: 1px solid var(--border);
        }
        .rail {
          padding: 16px;
          border-radius: 16px;
          border: 1px solid var(--border);
          background: rgba(255, 248, 237, 0.85);
          box-shadow: 0 8px 24px var(--shadow);
          position: sticky;
          top: 16px;
        }
        .rail-title {
          font-size: 1rem;
          font-weight: 700;
          margin-bottom: 8px;
        }
        .rail-row {
          display: flex;
          justify-content: space-between;
          gap: 8px;
          font-size: 0.85rem;
          color: var(--muted);
          margin: 6px 0;
        }
        .rail-divider {
          height: 1px;
          background: var(--border);
          margin: 12px 0;
        }
        .pill {
          padding: 2px 10px;
          border-radius: 999px;
          font-size: 0.7rem;
          letter-spacing: 0.02em;
          font-weight: 700;
        }
        .pill-idle {
          background: #efe2d2;
          color: #6b5b4b;
        }
        .pill-running {
          background: #2a6f5e;
          color: #fff9f2;
        }
        .side-card {
          padding: 16px;
          border-radius: 16px;
          border: 1px solid var(--border);
          background: rgba(255, 248, 237, 0.85);
          box-shadow: 0 8px 24px var(--shadow);
          margin-top: 16px;
        }
        .rail-item {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.95rem;
          color: var(--muted);
          margin: 6px 0;
        }
        .rail-note {
          margin-top: 12px;
          font-size: 0.85rem;
          color: var(--muted);
        }
        .rail-dot {
          width: 10px;
          height: 10px;
          border-radius: 999px;
          display: inline-block;
        }
        div[data-testid="stButton"] > button {
          background: var(--accent);
          color: #fff9f2;
          border-radius: 999px;
          border: none;
          padding: 0.5rem 1.2rem;
        }
        div[data-testid="stButton"] > button:hover {
          background: #bf5b30;
          color: #fff9f2;
        }
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stFileUploader"] section {
          background: #fffdf8;
          border: 1px solid var(--border);
          border-radius: 12px;
        }
        div[data-testid="stDataFrame"] {
          border: 1px solid var(--border);
          border-radius: 12px;
          overflow: hidden;
        }
        @keyframes rise {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _load_env_defaults() -> dict:
    if not ENV_PATH.exists():
        return {}
    return dict(dotenv_values(ENV_PATH))


def _save_env_value(key: str, value: str) -> None:
    set_key(str(ENV_PATH), key, value)
    os.environ[key] = value


def _resolve_site_language_map_path(path_value: str = "") -> Path:
    candidate = (path_value or "").strip()
    if not candidate:
        return DEFAULT_SITE_LANGUAGE_MAP_PATH
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = APP_DIR / path
    return path


def _site_language_map_to_raw_text(mapping: Dict[str, str]) -> str:
    return "\n".join(f"{site}:{lang}" for site, lang in sorted(mapping.items()))


def load_site_language_map_raw(path_value: str = "") -> str:
    path = _resolve_site_language_map_path(path_value)
    mapping = load_site_language_map_from_file(str(path))
    return _site_language_map_to_raw_text(mapping)


def save_site_language_map_json(site_language_map_raw: str, path_value: str = "") -> str:
    path = _resolve_site_language_map_path(path_value)
    mapping = parse_site_language_map(site_language_map_raw or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def initialize_site_language_map_session(env_defaults: dict) -> None:
    env_map_raw = (env_defaults.get("SITE_LANGUAGE_MAP", "") or "").strip() if env_defaults else ""
    configured_path = (
        (env_defaults.get("SITE_LANGUAGE_MAP_FILE", "") if env_defaults else "")
        or os.getenv("SITE_LANGUAGE_MAP_FILE", "")
    )
    resolved_path = str(_resolve_site_language_map_path(configured_path))
    os.environ["SITE_LANGUAGE_MAP_FILE"] = resolved_path
    if not Path(resolved_path).exists():
        try:
            save_site_language_map_json(env_map_raw, resolved_path)
        except OSError:
            pass
    if st.session_state.get("site_language_map_raw", "") != "":
        return
    file_map_raw = load_site_language_map_raw(resolved_path)
    if env_map_raw and file_map_raw:
        merged_map = {
            **parse_site_language_map(file_map_raw),
            **parse_site_language_map(env_map_raw),
        }
        st.session_state["site_language_map_raw"] = _site_language_map_to_raw_text(merged_map)
        return
    st.session_state["site_language_map_raw"] = env_map_raw or file_map_raw


def save_sheet_settings(sheet_url: str, sheet_tab: str, credentials_path: str, ready_value: str) -> None:
    _save_env_value("GOOGLE_SHEET_URL", sheet_url)
    _save_env_value("GOOGLE_SHEET_TAB", sheet_tab or "")
    _save_env_value("GOOGLE_SHEET_CREDENTIALS", credentials_path)
    _save_env_value("GOOGLE_SHEET_READY_VALUE", ready_value or "")


def maybe_auto_save_sheet_settings(
    sheet_url: str,
    sheet_tab: str,
    credentials_path: str,
    ready_value: str,
) -> bool:
    if not sheet_url or not credentials_path:
        return False
    snapshot = (sheet_url, sheet_tab or "", credentials_path, ready_value or "")
    if st.session_state.get("sheet_settings_saved") == snapshot:
        return False
    save_sheet_settings(
        sheet_url=sheet_url,
        sheet_tab=sheet_tab,
        credentials_path=credentials_path,
        ready_value=ready_value,
    )
    st.session_state["sheet_settings_saved"] = snapshot
    st.session_state["sheet_settings_saved_at"] = datetime.now()
    return True


def save_language_settings(
    output_language_override: str,
    default_output_language: str,
    site_language_map_raw: str,
) -> None:
    site_language_map_file = save_site_language_map_json(
        site_language_map_raw,
        os.getenv("SITE_LANGUAGE_MAP_FILE", ""),
    )
    _save_env_value("OUTPUT_LANGUAGE", (output_language_override or "").strip())
    _save_env_value("DEFAULT_OUTPUT_LANGUAGE", (default_output_language or "en").strip() or "en")
    _save_env_value("SITE_LANGUAGE_MAP", (site_language_map_raw or "").strip())
    _save_env_value("SITE_LANGUAGE_MAP_FILE", site_language_map_file)


def apply_language_settings_to_env(
    output_language_override: str,
    default_output_language: str,
    site_language_map_raw: str,
) -> None:
    os.environ["OUTPUT_LANGUAGE"] = (output_language_override or "").strip()
    os.environ["DEFAULT_OUTPUT_LANGUAGE"] = (default_output_language or "en").strip() or "en"
    os.environ["SITE_LANGUAGE_MAP"] = (site_language_map_raw or "").strip()
    os.environ["SITE_LANGUAGE_MAP_FILE"] = str(
        _resolve_site_language_map_path(os.getenv("SITE_LANGUAGE_MAP_FILE", ""))
    )


def ensure_midjourney_session_env() -> None:
    if os.getenv("MIDJOURNEY_SESSION_ID"):
        return
    session_id = st.session_state.get("midjourney_session_id")
    if not session_id:
        session_id = f"ui-{os.getpid()}"
        st.session_state["midjourney_session_id"] = session_id
    os.environ["MIDJOURNEY_SESSION_ID"] = session_id


def _resolve_path(value: str, base: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return path


def _sessionize_file(path: Path, session_id: str) -> Path:
    if path.suffix:
        return path.with_name(f"{path.stem}-{session_id}{path.suffix}")
    return Path(f"{path}-{session_id}")


def reset_midjourney_session() -> Dict[str, List[str] | str]:
    session_id = os.getenv("MIDJOURNEY_SESSION_ID") or st.session_state.get("midjourney_session_id") or ""
    if not session_id:
        session_id = f"ui-{os.getpid()}"

    profile_root = os.getenv("MIDJOURNEY_PROFILE_DIR", ".playwright/discord-profile")
    profile_root_path = _resolve_path(profile_root, APP_DIR)
    profile_dir = profile_root_path / session_id if session_id else profile_root_path

    storage_state_raw = os.getenv("MIDJOURNEY_STORAGE_STATE", "").strip()
    storage_state_path = None
    if storage_state_raw:
        storage_state_path = _resolve_path(storage_state_raw, APP_DIR)
        if session_id:
            storage_state_path = _sessionize_file(storage_state_path, session_id)

    removed: List[str] = []
    errors: List[str] = []
    for target in [profile_dir, storage_state_path]:
        if not target or not target.exists():
            continue
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            removed.append(str(target))
        except Exception as exc:
            errors.append(f"{target}: {exc}")

    new_session_id = f"ui-{os.getpid()}-{uuid4().hex[:8]}"
    st.session_state["midjourney_session_id"] = new_session_id
    os.environ["MIDJOURNEY_SESSION_ID"] = new_session_id

    return {
        "old_session_id": session_id,
        "new_session_id": new_session_id,
        "removed": removed,
        "errors": errors,
    }


def maybe_load_sheet_tabs(sheet_url: str, credentials_path: str) -> None:
    if not sheet_url or not credentials_path:
        return
    source = (sheet_url, credentials_path)
    if st.session_state.get("sheet_tabs_source") == source and st.session_state.get("sheet_tabs"):
        return
    try:
        st.session_state["sheet_tabs"] = list_sheet_worksheets(sheet_url, credentials_path)
        st.session_state["sheet_tabs_source"] = source
        st.session_state["sheet_tabs_error"] = ""
        if st.session_state["sheet_tabs"] and not st.session_state.get("sheet_tab"):
            st.session_state["sheet_tab"] = st.session_state["sheet_tabs"][0]
    except Exception as exc:
        st.session_state["sheet_tabs_error"] = str(exc)
        st.session_state["sheet_tabs_source"] = source


def maybe_set_default_sheet_credentials_path() -> None:
    if st.session_state.get("sheet_credentials_path"):
        return
    if DEFAULT_SHEET_CREDENTIALS_PATH.exists():
        st.session_state["sheet_credentials_path"] = str(DEFAULT_SHEET_CREDENTIALS_PATH)


def upsert_site_language_map(raw_map: str, site_key: str, language_code: str) -> str:
    site = (site_key or "").strip().lower()
    lang = (language_code or "").strip()
    if not site or not lang:
        return (raw_map or "").strip()
    if "://" in site:
        parsed = urllib.parse.urlparse(site)
        site = parsed.netloc or parsed.path or ""
    site = site.strip().strip("/")
    if site.startswith("www."):
        site = site[4:]
    if not site:
        return (raw_map or "").strip()

    mapping = parse_site_language_map(raw_map or "")
    normalized_lang_entry = parse_site_language_map(f"example.local:{lang}")
    normalized_lang = normalized_lang_entry.get("example.local", "")
    if not normalized_lang:
        return (raw_map or "").strip()
    mapping[site] = normalized_lang
    return "\n".join(f"{k}:{v}" for k, v in sorted(mapping.items()))


def apply_pending_site_language_map_update() -> None:
    pending_value = st.session_state.pop("site_language_map_raw_pending", None)
    if isinstance(pending_value, str):
        st.session_state["site_language_map_raw"] = pending_value


def _normalize_site_key_for_display(value: str) -> str:
    site = (value or "").strip().lower()
    if not site:
        return ""
    if "://" in site:
        parsed = urllib.parse.urlparse(site)
        site = parsed.netloc or parsed.path or ""
    site = site.strip().strip("/")
    if site.startswith("www."):
        site = site[4:]
    return site


def render_domain_language_summary(sheet_tab: str) -> None:
    st.markdown("**Domain Languages**")
    st.caption(
        f"Local JSON map: `{_resolve_site_language_map_path(os.getenv('SITE_LANGUAGE_MAP_FILE', ''))}`"
    )
    mapping = {
        **DEFAULT_SITE_LANGUAGE_MAP,
        **load_site_language_map_from_file(os.getenv("SITE_LANGUAGE_MAP_FILE", "")),
        **parse_site_language_map(st.session_state.get("site_language_map_raw", "")),
    }
    if mapping:
        markdown_rows = ["| Domain | Language |", "| --- | --- |"]
        for domain, language in sorted(mapping.items()):
            markdown_rows.append(f"| `{domain}` | `{language}` |")
        st.markdown("\n".join(markdown_rows))
    else:
        st.caption("No domain language mappings found.")

    resolved_output_language = resolve_output_language(
        sheet_tab=sheet_tab,
        explicit_language=st.session_state.get("output_language_override", ""),
        site_language_map_raw=st.session_state.get("site_language_map_raw", ""),
        default_language=st.session_state.get("default_output_language", "en"),
    )
    domain_label = _normalize_site_key_for_display(sheet_tab) or "(not set)"
    st.caption(f"Current domain language: `{domain_label}` -> `{resolved_output_language}`")


def render_hero(kicker: str, title: str, copy: str) -> None:
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-kicker">{kicker}</div>
          <div class="hero-title">{title}</div>
          <p class="hero-copy">
            {copy}
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_pins_page() -> None:
    inject_styles()
    render_hero(
        kicker="Recipe Pipeline",
        title="Pin to Recipe System",
        copy=(
            "The engine extracts recipe titles and visit links from Pinterest pins, "
            "builds the batch file, and runs the main generator in one flow."
        ),
    )

    if "pins_text" not in st.session_state:
        st.session_state["pins_text"] = load_text_file(DEFAULT_PINS_PATH)
    if "pin_rows" not in st.session_state:
        st.session_state["pin_rows"] = []
    if "batch_rows" not in st.session_state:
        st.session_state["batch_rows"] = []
    if "output_rows" not in st.session_state:
        st.session_state["output_rows"] = []
    if "generator_log" not in st.session_state:
        st.session_state["generator_log"] = ""
    if "batch_stats" not in st.session_state:
        st.session_state["batch_stats"] = None
    if "drop_missing" not in st.session_state:
        st.session_state["drop_missing"] = False
    if "input_path" not in st.session_state:
        st.session_state["input_path"] = str(DEFAULT_INPUT_PATH)
    if "sheet_tabs" not in st.session_state:
        st.session_state["sheet_tabs"] = []
    if "sheet_credentials_path" not in st.session_state:
        st.session_state["sheet_credentials_path"] = ""
    if "sheet_tab" not in st.session_state:
        st.session_state["sheet_tab"] = ""
    if "sheet_tabs_error" not in st.session_state:
        st.session_state["sheet_tabs_error"] = ""
    if "sheet_tabs_source" not in st.session_state:
        st.session_state["sheet_tabs_source"] = None
    if "sheet_url" not in st.session_state:
        st.session_state["sheet_url"] = ""
    if "sheet_ready_value" not in st.session_state:
        st.session_state["sheet_ready_value"] = ""
    if "sheet_settings_saved" not in st.session_state:
        st.session_state["sheet_settings_saved"] = None
    if "sheet_settings_saved_at" not in st.session_state:
        st.session_state["sheet_settings_saved_at"] = None
    if "output_language_override" not in st.session_state:
        st.session_state["output_language_override"] = ""
    if "default_output_language" not in st.session_state:
        st.session_state["default_output_language"] = "en"
    if "site_language_map_raw" not in st.session_state:
        st.session_state["site_language_map_raw"] = ""
    if "active_run" not in st.session_state:
        st.session_state["active_run"] = ""
    if "last_step_one" not in st.session_state:
        st.session_state["last_step_one"] = {}
    if "last_step_two" not in st.session_state:
        st.session_state["last_step_two"] = {}
    if "pin_timeout" not in st.session_state:
        st.session_state["pin_timeout"] = 20.0
    if "pins_source" not in st.session_state:
        st.session_state["pins_source"] = "Paste/Type"
    if "pins_source_loaded" not in st.session_state:
        st.session_state["pins_source_loaded"] = ""
    if "use_openai" not in st.session_state:
        st.session_state["use_openai"] = True
    if "openai_model" not in st.session_state:
        st.session_state["openai_model"] = "gpt-5-mini"
    if "save_batch_csv" not in st.session_state:
        st.session_state["save_batch_csv"] = True
    if "output_path" not in st.session_state:
        st.session_state["output_path"] = str(DEFAULT_OUTPUT_PATH)
    if "overwrite_output" not in st.session_state:
        st.session_state["overwrite_output"] = True
    if "use_live_input" not in st.session_state:
        st.session_state["use_live_input"] = True
    if "log_level" not in st.session_state:
        st.session_state["log_level"] = "INFO"

    env_defaults = _load_env_defaults()
    if env_defaults:
        if st.session_state.get("openai_model") in {"", "gpt-3.5-turbo", "gpt-5-mini"}:
            st.session_state["openai_model"] = (
                env_defaults.get("OPENAI_MODEL")
                or env_defaults.get("MODEL_NAME")
                or st.session_state.get("openai_model")
                or "gpt-5-mini"
            )
        if not st.session_state.get("sheet_url"):
            st.session_state["sheet_url"] = env_defaults.get("GOOGLE_SHEET_URL", "") or ""
        if not st.session_state.get("sheet_tab"):
            st.session_state["sheet_tab"] = env_defaults.get("GOOGLE_SHEET_TAB", "") or ""
        if not st.session_state.get("sheet_credentials_path"):
            st.session_state["sheet_credentials_path"] = (
                env_defaults.get("GOOGLE_SHEET_CREDENTIALS", "") or ""
            )
        if not st.session_state.get("sheet_ready_value"):
            st.session_state["sheet_ready_value"] = (
                env_defaults.get("GOOGLE_SHEET_READY_VALUE", "") or ""
            )
        if st.session_state.get("output_language_override", "") == "":
            st.session_state["output_language_override"] = env_defaults.get("OUTPUT_LANGUAGE", "") or ""
        if st.session_state.get("default_output_language", "") in {"", "en"}:
            st.session_state["default_output_language"] = (
                env_defaults.get("DEFAULT_OUTPUT_LANGUAGE", "") or st.session_state.get("default_output_language") or "en"
            )
    initialize_site_language_map_session(env_defaults)
    maybe_set_default_sheet_credentials_path()
    apply_pending_site_language_map_update()
    apply_language_settings_to_env(
        st.session_state.get("output_language_override", ""),
        st.session_state.get("default_output_language", "en"),
        st.session_state.get("site_language_map_raw", ""),
    )
    os.environ.setdefault("PIPELINE_PAUSE_FILE", str(PAUSE_FILE))
    ensure_midjourney_session_env()

    active_run = st.session_state.get("active_run", "")

    progress_container = None
    run_panel_container = None

    def refresh_progress_panel() -> None:
        if progress_container is None:
            return
        render_progress(
            bool(st.session_state.get("pin_rows")),
            bool(st.session_state.get("batch_rows")),
            bool(st.session_state.get("output_rows")),
            container=progress_container,
        )

    def refresh_run_panel(active_override: Optional[str] = None) -> None:
        if run_panel_container is None:
            return
        current_active = active_override if active_override is not None else st.session_state.get("active_run", "")
        render_run_panel(
            active_run=current_active,
            last_step_one=st.session_state.get("last_step_one", {}),
            last_step_two=st.session_state.get("last_step_two", {}),
            input_estimate=estimate_pin_count(st.session_state.get("pins_text", "")),
            extracted_rows_count=len(st.session_state.get("pin_rows", [])),
            batch_rows_count=len(st.session_state.get("batch_rows", [])),
            step_one_timeout=float(st.session_state.get("pin_timeout") or 0),
            input_label="Pins in input",
            extracted_label="Extracted pins",
            container=run_panel_container,
        )

    left, right = st.columns([1, 3], gap="large")
    with left:
        progress_container = st.empty()
        refresh_progress_panel()
        run_panel_container = st.empty()
        refresh_run_panel(active_override=active_run)

    with right:
        st.markdown('<div class="section-title">Engine</div>', unsafe_allow_html=True)
        st.caption("One click run: extract pins -> build batch -> run generator. Advanced settings are tucked below.")

        engine_left, engine_right = st.columns([3, 2], gap="large")
        with engine_left:
            st.text_area("Pins input", key="pins_text", height=240)
        with engine_right:
            source_mode = st.radio(
                "Pins source",
                ["Paste/Type", "Upload .txt", "Load pins.txt"],
                horizontal=True,
                key="pins_source",
            )
            if source_mode == "Upload .txt":
                uploaded = st.file_uploader("Upload pin list", type=["txt"])
                if uploaded:
                    st.session_state["pins_text"] = uploaded.read().decode("utf-8", errors="ignore")
                    st.session_state["pins_source_loaded"] = "upload"
            elif source_mode == "Load pins.txt":
                if st.session_state.get("pins_source_loaded") != "pins.txt":
                    st.session_state["pins_text"] = load_text_file(DEFAULT_PINS_PATH)
                    st.session_state["pins_source_loaded"] = "pins.txt"

            use_openai = st.checkbox(
                "Use OpenAI for extraction",
                value=True,
                key="use_openai",
            )
            drop_missing = st.checkbox(
                "Only keep rows with Recipe Name and Recipe URL",
                key="drop_missing",
                help="Rows missing a visit URL will be excluded. Uncheck to include all rows (but pipeline will only process rows with URLs).",
            )
            pin_count_estimate = estimate_pin_count(st.session_state.get("pins_text", ""))
            if pin_count_estimate:
                st.caption(
                    f"Estimated pins in input: {pin_count_estimate}. "
                    f"Upper bound time if every pin hits timeout: "
                    f"{format_duration(pin_count_estimate * float(st.session_state.get('pin_timeout') or 0))}."
                )

        st.markdown("**Step 2 Sheet Target**")
        sheet_url = st.text_input("Google Sheet URL", key="sheet_url")
        credentials_upload = st.file_uploader(
            "Service account JSON",
            type=["json"],
            key="sheet_credentials_upload",
        )
        if credentials_upload:
            SECRETS_DIR.mkdir(parents=True, exist_ok=True)
            with DEFAULT_SHEET_CREDENTIALS_PATH.open("wb") as handle:
                handle.write(credentials_upload.read())
            st.session_state["sheet_credentials_path"] = str(DEFAULT_SHEET_CREDENTIALS_PATH)
            st.info(f"Saved credentials to {DEFAULT_SHEET_CREDENTIALS_PATH}")
        sheet_credentials_path = st.text_input(
            "Credentials path",
            key="sheet_credentials_path",
        )
        maybe_load_sheet_tabs(sheet_url, sheet_credentials_path)
        load_tabs_disabled = not (sheet_url and sheet_credentials_path)
        if st.button("Reload sheet tabs", disabled=load_tabs_disabled):
            try:
                st.session_state["sheet_tabs"] = list_sheet_worksheets(
                    sheet_url, sheet_credentials_path
                )
                st.session_state["sheet_tabs_source"] = (sheet_url, sheet_credentials_path)
                st.session_state["sheet_tabs_error"] = ""
                if st.session_state["sheet_tabs"]:
                    st.session_state["sheet_tab"] = st.session_state["sheet_tabs"][0]
            except Exception as exc:
                st.session_state["sheet_tabs_error"] = str(exc)
                st.error(f"Failed to load worksheet list: {exc}")
        if st.session_state.get("sheet_tabs_error"):
            st.warning(f"Sheet tabs could not be loaded: {st.session_state['sheet_tabs_error']}")
        elif sheet_url and sheet_credentials_path and not st.session_state["sheet_tabs"]:
            st.caption("No tabs loaded yet. Click `Reload sheet tabs` or verify sheet permissions/credentials.")
        elif not sheet_url or not sheet_credentials_path:
            st.caption("Add a Google Sheet URL and credentials path to load a tab dropdown.")
        if st.session_state["sheet_tabs"]:
            sheet_tab = st.selectbox(
                "Worksheet/tab",
                st.session_state["sheet_tabs"],
                index=st.session_state["sheet_tabs"].index(st.session_state["sheet_tab"])
                if st.session_state["sheet_tab"] in st.session_state["sheet_tabs"]
                else 0,
            )
            st.session_state["sheet_tab"] = sheet_tab
        else:
            sheet_tab = st.text_input(
                "Worksheet/tab (optional)",
                value=st.session_state.get("sheet_tab", ""),
            )
            st.session_state["sheet_tab"] = sheet_tab

        apply_language_settings_to_env(
            st.session_state.get("output_language_override", ""),
            st.session_state.get("default_output_language", "en"),
            st.session_state.get("site_language_map_raw", ""),
        )
        render_domain_language_summary(st.session_state.get("sheet_tab", ""))
        sheet_ready_value = st.text_input(
            "Ready column value (optional)",
            key="sheet_ready_value",
            help="If your sheet has a Ready column, this value will be written. Leave blank to keep it empty.",
        )
        saved = maybe_auto_save_sheet_settings(
            sheet_url,
            st.session_state.get("sheet_tab", ""),
            sheet_credentials_path,
            sheet_ready_value,
        )
        if saved:
            st.caption("Sheet settings saved.")

        pause_col, run_col = st.columns([1, 3], gap="small")
        with pause_col:
            paused = PAUSE_FILE.exists()
            if st.button("Pause"):
                PAUSE_FILE.write_text("paused", encoding="utf-8")
                paused = True
            if st.button("Resume"):
                if PAUSE_FILE.exists():
                    PAUSE_FILE.unlink()
                paused = False
            st.caption("Paused" if paused else "Running")
        with run_col:
            run_engine = st.button("Run Engine", type="primary", disabled=bool(active_run))
        if run_engine:
            st.session_state["generator_log"] = ""
            st.session_state["active_run"] = "step1"
            refresh_run_panel(active_override="step1")
            step_one_started = datetime.now()
            step_one_start = time.perf_counter()
            step_one_status = "success"
            try:
                with st.status("Step 1: Extract pins", expanded=True) as status:
                    progress = st.progress(0.05, text="Extracting pins")
                    st.session_state["pin_rows"] = run_pin_extract(
                        st.session_state["pins_text"],
                        timeout=float(st.session_state.get("pin_timeout") or 20.0),
                        use_openai=st.session_state.get("use_openai", True),
                        openai_model=st.session_state.get("openai_model", "gpt-3.5-turbo"),
                    )
                    progress.progress(0.45, text="Building batch rows")
                    st.session_state["output_rows"] = []
                    for path in (DEFAULT_INPUT_PATH, DEFAULT_OUTPUT_PATH):
                        try:
                            if path.exists():
                                path.unlink()
                        except OSError:
                            pass
                    batch_rows, stats = build_batch_rows(
                        st.session_state["pin_rows"],
                        drop_missing=st.session_state.get("drop_missing", False),
                    )
                    st.session_state["batch_rows"] = batch_rows
                    st.session_state["batch_stats"] = stats
                    progress.progress(0.75, text="Saving batch CSV")
                    input_path = Path(st.session_state.get("input_path") or str(DEFAULT_INPUT_PATH))
                    if st.session_state.get("save_batch_csv", True):
                        try:
                            write_csv(
                                input_path,
                                st.session_state["batch_rows"],
                                ["Recipe Name", "Pinterest URL", "Recipe URL"],
                            )
                            progress.progress(1.0, text="Step 1 complete")
                            status.update(label="Step 1 complete", state="complete")
                            st.success(
                                f"Extracted {len(st.session_state['pin_rows'])} pins. "
                                f"Built {len(st.session_state['batch_rows'])} batch rows and saved to {input_path}."
                            )
                        except Exception as exc:
                            status.update(label="Step 1 finished with warnings", state="complete")
                            st.warning(
                                f"Extracted {len(st.session_state['pin_rows'])} pins and built "
                                f"{len(st.session_state['batch_rows'])} batch rows, "
                                f"but failed to save CSV: {exc}"
                            )
                    else:
                        progress.progress(1.0, text="Step 1 complete")
                        status.update(label="Step 1 complete", state="complete")
                        st.success(
                            f"Extracted {len(st.session_state['pin_rows'])} pins. "
                            f"Built {len(st.session_state['batch_rows'])} batch rows."
                        )
            except Exception as exc:
                step_one_status = "error"
                st.error(str(exc))
            finally:
                st.session_state["last_step_one"] = {
                    "completed_at": step_one_started,
                    "duration": time.perf_counter() - step_one_start,
                    "status": step_one_status,
                }
                refresh_progress_panel()

            if step_one_status == "success" and st.session_state["batch_rows"]:
                st.session_state["active_run"] = "step2"
                refresh_run_panel(active_override="step2")
                step_two_started = datetime.now()
                step_two_start = time.perf_counter()
                step_two_status = "success"
                try:
                    output_path_input = st.session_state.get("output_path") or str(DEFAULT_OUTPUT_PATH)
                    if not output_path_input.strip():
                        output_path_input = str(DEFAULT_OUTPUT_PATH)
                    output_path = Path(output_path_input)
                    log_level = st.session_state.get("log_level", "INFO")
                    overwrite_output = st.session_state.get("overwrite_output", True)
                    use_live_input = st.session_state.get("use_live_input", True)

                    sheet_url = st.session_state.get("sheet_url", "")
                    sheet_credentials_path = st.session_state.get("sheet_credentials_path", "")
                    sheet_tab = st.session_state.get("sheet_tab", "")
                    sheet_ready_value = st.session_state.get("sheet_ready_value", "")

                    if output_path.is_dir() or str(output_path) == ".":
                        step_two_status = "error"
                        st.error("Output path must be a file, not a directory. Please specify a CSV filename.")
                    else:
                        can_run = True
                        if sheet_url and not sheet_credentials_path:
                            st.error("Google Sheet URL provided but credentials JSON is missing.")
                            can_run = False
                        if not overwrite_output and output_path.exists():
                            st.warning(
                                "Output file already exists. Results will be appended, which can mix older runs "
                                "with the current batch. Enable overwrite to keep only the latest results."
                            )
                        if overwrite_output and output_path.exists():
                            try:
                                output_path.unlink()
                            except OSError as exc:
                                step_two_status = "error"
                                st.error(f"Failed to remove existing output: {exc}")

                        temp_dir = None
                        input_path = Path(st.session_state.get("input_path") or str(DEFAULT_INPUT_PATH))
                        run_input = input_path
                        if use_live_input:
                            try:
                                temp_dir = tempfile.TemporaryDirectory()
                                run_input = Path(temp_dir.name) / "batch_input.csv"
                                write_csv(
                                    run_input,
                                    st.session_state["batch_rows"],
                                    ["Recipe Name", "Pinterest URL", "Recipe URL"],
                                )
                            except Exception as exc:
                                step_two_status = "error"
                                st.error(f"Failed to prepare live input: {exc}")
                                can_run = False
                        elif not input_path.exists():
                            step_two_status = "error"
                            st.error("Batch input file not found. Save Step 1 or enable live input.")
                            can_run = False

                        if can_run and run_input.exists():
                            log_placeholder = st.empty()
                            with st.status("Step 2: Run generator", expanded=True) as status:
                                progress = st.progress(0.0, text="Starting generator")
                                returncode, combined_log = run_generator_stream(
                                    run_input,
                                    output_path,
                                    log_level,
                                    log_placeholder=log_placeholder,
                                    progress_placeholder=progress,
                                    total_targets=len(st.session_state["batch_rows"]),
                                    sheet_url=sheet_url,
                                    sheet_tab=sheet_tab,
                                    sheet_credentials=sheet_credentials_path,
                                    sheet_ready_value=sheet_ready_value,
                                )
                                st.session_state["generator_log"] = combined_log
                                if returncode != 0:
                                    step_two_status = "error"
                                    status.update(label="Generator failed", state="error")
                                    st.error("Generator failed. Check logs for details.")
                                else:
                                    status.update(label="Generator finished", state="complete")
                                    st.success("Generator finished.")
                                if output_path.exists():
                                    try:
                                        st.session_state["output_rows"] = read_csv_rows(output_path)
                                    except Exception as exc:
                                        step_two_status = "error"
                                        st.error(f"Failed to read output CSV: {exc}")
                        if temp_dir is not None:
                            temp_dir.cleanup()
                except Exception as exc:
                    step_two_status = "error"
                    st.error(str(exc))
                finally:
                    st.session_state["last_step_two"] = {
                        "completed_at": step_two_started,
                        "duration": time.perf_counter() - step_two_start,
                        "status": step_two_status,
                    }
                    st.session_state["active_run"] = ""
                    refresh_run_panel(active_override="")
                    refresh_progress_panel()
            else:
                if step_one_status == "success" and not st.session_state["batch_rows"]:
                    st.warning(
                        "No valid batch rows were built. Add pins with recipe URLs or adjust the filter."
                    )
                st.session_state["active_run"] = ""
                refresh_run_panel(active_override="")
                refresh_progress_panel()

        with st.expander("Advanced settings", expanded=False):
            st.markdown("**Extraction**")
            st.text_input(
                "OpenAI model",
                value="gpt-3.5-turbo",
                key="openai_model",
                disabled=not use_openai,
            )
            st.number_input(
                "Pin timeout (seconds)",
                min_value=5.0,
                max_value=60.0,
                value=20.0,
                key="pin_timeout",
            )

            st.markdown("**Batch & Output**")
            st.text_input(
                "Batch input path",
                key="input_path",
                value=str(DEFAULT_INPUT_PATH),
            )
            st.checkbox("Save batch CSV to path", value=True, key="save_batch_csv")
            st.text_input("Output CSV path", key="output_path", value=str(DEFAULT_OUTPUT_PATH))
            st.selectbox("Log level", ["INFO", "DEBUG", "WARNING", "ERROR"], index=0, key="log_level")
            st.checkbox("Overwrite output before run", value=True, key="overwrite_output")
            st.checkbox("Use live batch data (no save needed)", value=True, key="use_live_input")

            st.markdown("**Midjourney Session (optional)**")
            st.caption(
                "If the Midjourney browser is stuck or showing about:blank, reset the session. "
                "Close any Midjourney/Playwright windows first."
            )
            current_session_id = os.getenv("MIDJOURNEY_SESSION_ID", "")
            if current_session_id:
                st.caption(f"Current session: `{current_session_id}`")
            if st.button("Reset Midjourney session"):
                result = reset_midjourney_session()
                if result["errors"]:
                    st.error("Reset completed with errors:\n" + "\n".join(result["errors"]))
                else:
                    st.success("Midjourney session reset.")
                if result["removed"]:
                    st.info("Removed session data:\n" + "\n".join(result["removed"]))
                st.info(f"New session: `{result['new_session_id']}`")

        if st.session_state["generator_log"]:
            with st.expander("Generator logs", expanded=False):
                st.caption(f"Showing the last {LOG_TAIL_LIMIT} lines from the most recent run.")
                st.code(st.session_state["generator_log"])

        with st.expander("Data preview", expanded=False):
            if st.session_state["pin_rows"]:
                total_pins = len(st.session_state["pin_rows"])
                with_urls = sum(
                    1
                    for row in st.session_state["pin_rows"]
                    if (row.get("visit_site_url") or "").strip()
                )
                missing_urls = total_pins - with_urls
                if with_urls == 0:
                    st.error(
                        "No external recipe URLs were found. These look like Pinterest-only pins "
                        "without a Visit link, so Step 2 cannot run. Try pins that have a Visit button."
                    )
                elif missing_urls > 0:
                    st.warning(
                        f"{missing_urls} of {total_pins} pins are missing external URLs and will be skipped in Step 2."
                    )
                display_rows = [
                    {
                        "recipe": row.get("recipe", ""),
                        "pinterest_url": row.get("pinterest_url", ""),
                        "visit_site_url": row.get("visit_site_url", ""),
                    }
                    for row in st.session_state["pin_rows"]
                ]
                safe_dataframe(display_rows, use_container_width=True)

            if st.session_state.get("batch_stats"):
                render_batch_stats(st.session_state["batch_stats"])

            if st.session_state["batch_rows"]:
                safe_dataframe(st.session_state["batch_rows"], use_container_width=True)

        with st.expander("Exports", expanded=False):
            if st.session_state["batch_rows"]:
                csv_data = rows_to_csv(
                    st.session_state["batch_rows"],
                    ["Recipe Name", "Pinterest URL", "Recipe URL"],
                )
                st.download_button(
                    "Download batch CSV",
                    data=csv_data,
                    file_name="batch_input.csv",
                    mime="text/csv",
                )

        st.markdown('<div class="section-title">Results</div>', unsafe_allow_html=True)
        if st.session_state["output_rows"]:
            safe_dataframe(st.session_state["output_rows"], use_container_width=True)
        elif st.session_state["batch_rows"]:
            safe_dataframe(st.session_state["batch_rows"], use_container_width=True)
        else:
            st.info("Run the engine to see results.")


def render_keywords_page() -> None:
    inject_styles()
    render_hero(
        kicker="Recipe Pipeline",
        title="Keyword to Recipe System",
        copy=(
            "The engine researches recipe candidates from your keywords, "
            "uses AI to pick the best match, builds the batch file, and runs the main generator."
        ),
    )

    if "keywords_text" not in st.session_state:
        st.session_state["keywords_text"] = load_text_file(DEFAULT_KEYWORDS_PATH)
    if "keyword_rows" not in st.session_state:
        st.session_state["keyword_rows"] = []
    if "kw_batch_rows" not in st.session_state:
        st.session_state["kw_batch_rows"] = []
    if "kw_output_rows" not in st.session_state:
        st.session_state["kw_output_rows"] = []
    if "kw_generator_log" not in st.session_state:
        st.session_state["kw_generator_log"] = ""
    if "kw_batch_stats" not in st.session_state:
        st.session_state["kw_batch_stats"] = None
    if "kw_drop_missing" not in st.session_state:
        st.session_state["kw_drop_missing"] = False
    if "kw_drop_missing_migrated" not in st.session_state:
        st.session_state["kw_drop_missing"] = False
        st.session_state["kw_drop_missing_migrated"] = True
    if "kw_input_path" not in st.session_state:
        st.session_state["kw_input_path"] = str(DEFAULT_KEYWORD_INPUT_PATH)
    if "kw_active_run" not in st.session_state:
        st.session_state["kw_active_run"] = ""
    if "kw_last_step_one" not in st.session_state:
        st.session_state["kw_last_step_one"] = {}
    if "kw_last_step_two" not in st.session_state:
        st.session_state["kw_last_step_two"] = {}
    if "kw_keyword_timeout" not in st.session_state:
        st.session_state["kw_keyword_timeout"] = 20.0
    if "keywords_source" not in st.session_state:
        st.session_state["keywords_source"] = "Paste/Type"
    if "keywords_source_loaded" not in st.session_state:
        st.session_state["keywords_source_loaded"] = ""
    if "kw_use_openai" not in st.session_state:
        st.session_state["kw_use_openai"] = True
    if "kw_skip_research" not in st.session_state:
        st.session_state["kw_skip_research"] = True
    if "kw_openai_model" not in st.session_state:
        st.session_state["kw_openai_model"] = "gpt-5-mini"
    if "kw_max_results" not in st.session_state:
        st.session_state["kw_max_results"] = 6
    if "kw_context_hint" not in st.session_state:
        st.session_state["kw_context_hint"] = ""
    if "kw_save_batch_csv" not in st.session_state:
        st.session_state["kw_save_batch_csv"] = True
    if "kw_output_path" not in st.session_state:
        st.session_state["kw_output_path"] = str(DEFAULT_KEYWORD_OUTPUT_PATH)
    if "kw_overwrite_output" not in st.session_state:
        st.session_state["kw_overwrite_output"] = True
    if "kw_use_live_input" not in st.session_state:
        st.session_state["kw_use_live_input"] = True
    if "kw_log_level" not in st.session_state:
        st.session_state["kw_log_level"] = "INFO"

    if "sheet_tabs" not in st.session_state:
        st.session_state["sheet_tabs"] = []
    if "sheet_credentials_path" not in st.session_state:
        st.session_state["sheet_credentials_path"] = ""
    if "sheet_tab" not in st.session_state:
        st.session_state["sheet_tab"] = ""
    if "sheet_tabs_error" not in st.session_state:
        st.session_state["sheet_tabs_error"] = ""
    if "sheet_tabs_source" not in st.session_state:
        st.session_state["sheet_tabs_source"] = None
    if "sheet_url" not in st.session_state:
        st.session_state["sheet_url"] = ""
    if "sheet_ready_value" not in st.session_state:
        st.session_state["sheet_ready_value"] = ""
    if "sheet_settings_saved" not in st.session_state:
        st.session_state["sheet_settings_saved"] = None
    if "sheet_settings_saved_at" not in st.session_state:
        st.session_state["sheet_settings_saved_at"] = None
    if "output_language_override" not in st.session_state:
        st.session_state["output_language_override"] = ""
    if "default_output_language" not in st.session_state:
        st.session_state["default_output_language"] = "en"
    if "site_language_map_raw" not in st.session_state:
        st.session_state["site_language_map_raw"] = ""

    env_defaults = _load_env_defaults()
    if env_defaults:
        if st.session_state.get("kw_openai_model") in {"", "gpt-3.5-turbo", "gpt-5-mini"}:
            st.session_state["kw_openai_model"] = (
                env_defaults.get("OPENAI_MODEL")
                or env_defaults.get("MODEL_NAME")
                or st.session_state.get("kw_openai_model")
                or "gpt-5-mini"
            )
        if not st.session_state.get("sheet_url"):
            st.session_state["sheet_url"] = env_defaults.get("GOOGLE_SHEET_URL", "") or ""
        if not st.session_state.get("sheet_tab"):
            st.session_state["sheet_tab"] = env_defaults.get("GOOGLE_SHEET_TAB", "") or ""
        if not st.session_state.get("sheet_credentials_path"):
            st.session_state["sheet_credentials_path"] = (
                env_defaults.get("GOOGLE_SHEET_CREDENTIALS", "") or ""
            )
        if not st.session_state.get("sheet_ready_value"):
            st.session_state["sheet_ready_value"] = (
                env_defaults.get("GOOGLE_SHEET_READY_VALUE", "") or ""
            )
        if st.session_state.get("output_language_override", "") == "":
            st.session_state["output_language_override"] = env_defaults.get("OUTPUT_LANGUAGE", "") or ""
        if st.session_state.get("default_output_language", "") in {"", "en"}:
            st.session_state["default_output_language"] = (
                env_defaults.get("DEFAULT_OUTPUT_LANGUAGE", "") or st.session_state.get("default_output_language") or "en"
            )
    initialize_site_language_map_session(env_defaults)

    maybe_set_default_sheet_credentials_path()
    apply_pending_site_language_map_update()
    apply_language_settings_to_env(
        st.session_state.get("output_language_override", ""),
        st.session_state.get("default_output_language", "en"),
        st.session_state.get("site_language_map_raw", ""),
    )
    os.environ.setdefault("PIPELINE_PAUSE_FILE", str(PAUSE_FILE))
    ensure_midjourney_session_env()

    active_run = st.session_state.get("kw_active_run", "")

    progress_container = None
    run_panel_container = None

    def refresh_progress_panel() -> None:
        if progress_container is None:
            return
        render_progress(
            bool(st.session_state.get("keyword_rows")),
            bool(st.session_state.get("kw_batch_rows")),
            bool(st.session_state.get("kw_output_rows")),
            container=progress_container,
        )

    def refresh_run_panel(active_override: Optional[str] = None) -> None:
        if run_panel_container is None:
            return
        current_active = active_override if active_override is not None else st.session_state.get(
            "kw_active_run", ""
        )
        render_run_panel(
            active_run=current_active,
            last_step_one=st.session_state.get("kw_last_step_one", {}),
            last_step_two=st.session_state.get("kw_last_step_two", {}),
            input_estimate=estimate_keyword_count(st.session_state.get("keywords_text", "")),
            extracted_rows_count=len(st.session_state.get("keyword_rows", [])),
            batch_rows_count=len(st.session_state.get("kw_batch_rows", [])),
            step_one_timeout=float(st.session_state.get("kw_keyword_timeout") or 0),
            input_label="Keywords in input",
            extracted_label="Researched rows",
            container=run_panel_container,
        )

    left, right = st.columns([1, 3], gap="large")
    with left:
        progress_container = st.empty()
        refresh_progress_panel()
        run_panel_container = st.empty()
        refresh_run_panel(active_override=active_run)

    with right:
        st.markdown('<div class="section-title">Engine</div>', unsafe_allow_html=True)
        st.caption(
            "One click run: keyword-only build or research -> build batch -> run generator. "
            "Advanced settings are tucked below."
        )

        engine_left, engine_right = st.columns([3, 2], gap="large")
        with engine_left:
            st.text_area("Keywords input (one per line)", key="keywords_text", height=240)
        with engine_right:
            source_mode = st.radio(
                "Keywords source",
                ["Paste/Type", "Upload .txt", "Load keywords.txt"],
                horizontal=True,
                key="keywords_source",
            )
            if source_mode == "Upload .txt":
                uploaded = st.file_uploader("Upload keyword list", type=["txt"], key="kw_keywords_upload")
                if uploaded:
                    st.session_state["keywords_text"] = uploaded.read().decode("utf-8", errors="ignore")
                    st.session_state["keywords_source_loaded"] = "upload"
            elif source_mode == "Load keywords.txt":
                if st.session_state.get("keywords_source_loaded") != "keywords.txt":
                    st.session_state["keywords_text"] = load_text_file(DEFAULT_KEYWORDS_PATH)
                    st.session_state["keywords_source_loaded"] = "keywords.txt"

            kw_use_openai = st.checkbox(
                "Use OpenAI for keyword-to-recipe selection",
                value=True,
                key="kw_use_openai",
            )
            st.checkbox(
                "Skip web research (AI from keywords only)",
                key="kw_skip_research",
                help="When enabled, Step 1 builds rows directly from your keyword lines without requiring URLs.",
            )
            kw_drop_missing = st.checkbox(
                "Only keep rows with Recipe Name and Recipe URL",
                key="kw_drop_missing",
                help="Disable this to allow keyword-only AI generation even when no Recipe URL is available.",
            )
            kw_count_estimate = estimate_keyword_count(st.session_state.get("keywords_text", ""))
            if kw_count_estimate:
                st.caption(
                    f"Estimated keywords in input: {kw_count_estimate}. "
                    f"Upper bound research time: "
                    f"{format_duration(kw_count_estimate * float(st.session_state.get('kw_keyword_timeout') or 0))}."
                )

        st.markdown("**Step 2 Sheet Target**")
        sheet_url = st.text_input("Google Sheet URL", key="sheet_url")
        credentials_upload = st.file_uploader(
            "Service account JSON",
            type=["json"],
            key="kw_sheet_credentials_upload",
        )
        if credentials_upload:
            SECRETS_DIR.mkdir(parents=True, exist_ok=True)
            with DEFAULT_SHEET_CREDENTIALS_PATH.open("wb") as handle:
                handle.write(credentials_upload.read())
            st.session_state["sheet_credentials_path"] = str(DEFAULT_SHEET_CREDENTIALS_PATH)
            st.info(f"Saved credentials to {DEFAULT_SHEET_CREDENTIALS_PATH}")
        sheet_credentials_path = st.text_input(
            "Credentials path",
            key="sheet_credentials_path",
        )
        maybe_load_sheet_tabs(sheet_url, sheet_credentials_path)
        load_tabs_disabled = not (sheet_url and sheet_credentials_path)
        if st.button("Reload sheet tabs", disabled=load_tabs_disabled, key="kw_reload_sheet_tabs"):
            try:
                st.session_state["sheet_tabs"] = list_sheet_worksheets(
                    sheet_url, sheet_credentials_path
                )
                st.session_state["sheet_tabs_source"] = (sheet_url, sheet_credentials_path)
                st.session_state["sheet_tabs_error"] = ""
                if st.session_state["sheet_tabs"]:
                    st.session_state["sheet_tab"] = st.session_state["sheet_tabs"][0]
            except Exception as exc:
                st.session_state["sheet_tabs_error"] = str(exc)
                st.error(f"Failed to load worksheet list: {exc}")
        if st.session_state.get("sheet_tabs_error"):
            st.warning(f"Sheet tabs could not be loaded: {st.session_state['sheet_tabs_error']}")
        elif sheet_url and sheet_credentials_path and not st.session_state["sheet_tabs"]:
            st.caption("No tabs loaded yet. Click `Reload sheet tabs` or verify sheet permissions/credentials.")
        elif not sheet_url or not sheet_credentials_path:
            st.caption("Add a Google Sheet URL and credentials path to load a tab dropdown.")
        if st.session_state["sheet_tabs"]:
            sheet_tab = st.selectbox(
                "Worksheet/tab",
                st.session_state["sheet_tabs"],
                index=st.session_state["sheet_tabs"].index(st.session_state["sheet_tab"])
                if st.session_state["sheet_tab"] in st.session_state["sheet_tabs"]
                else 0,
                key="kw_sheet_tab_select",
            )
            st.session_state["sheet_tab"] = sheet_tab
        else:
            sheet_tab = st.text_input(
                "Worksheet/tab (optional)",
                value=st.session_state.get("sheet_tab", ""),
                key="kw_sheet_tab_input",
            )
            st.session_state["sheet_tab"] = sheet_tab

        apply_language_settings_to_env(
            st.session_state.get("output_language_override", ""),
            st.session_state.get("default_output_language", "en"),
            st.session_state.get("site_language_map_raw", ""),
        )
        render_domain_language_summary(st.session_state.get("sheet_tab", ""))
        sheet_ready_value = st.text_input(
            "Ready column value (optional)",
            key="sheet_ready_value",
            help="If your sheet has a Ready column, this value will be written. Leave blank to keep it empty.",
        )
        saved = maybe_auto_save_sheet_settings(
            sheet_url,
            st.session_state.get("sheet_tab", ""),
            sheet_credentials_path,
            sheet_ready_value,
        )
        if saved:
            st.caption("Sheet settings saved.")

        pause_col, run_col = st.columns([1, 3], gap="small")
        with pause_col:
            paused = PAUSE_FILE.exists()
            if st.button("Pause", key="kw_pause"):
                PAUSE_FILE.write_text("paused", encoding="utf-8")
                paused = True
            if st.button("Resume", key="kw_resume"):
                if PAUSE_FILE.exists():
                    PAUSE_FILE.unlink()
                paused = False
            st.caption("Paused" if paused else "Running")
        with run_col:
            run_engine = st.button("Run Engine", type="primary", disabled=bool(active_run), key="kw_run_engine")
        if run_engine:
            st.session_state["kw_generator_log"] = ""
            st.session_state["kw_active_run"] = "step1"
            refresh_run_panel(active_override="step1")
            step_one_started = datetime.now()
            step_one_start = time.perf_counter()
            step_one_status = "success"
            try:
                step_one_label = (
                    "Step 1: Build keyword-only rows"
                    if st.session_state.get("kw_skip_research", True)
                    else "Step 1: Research keywords"
                )
                with st.status(step_one_label, expanded=True) as status:
                    if st.session_state.get("kw_skip_research", True):
                        progress = st.progress(0.4, text="Building rows from keywords")
                        st.session_state["keyword_rows"] = build_keyword_only_rows(
                            st.session_state["keywords_text"]
                        )
                    else:
                        progress = st.progress(0.05, text="Researching keywords")
                        st.session_state["keyword_rows"] = run_keyword_extract(
                            st.session_state["keywords_text"],
                            timeout=float(st.session_state.get("kw_keyword_timeout") or 20.0),
                            max_results=int(st.session_state.get("kw_max_results") or 6),
                            use_openai=st.session_state.get("kw_use_openai", True),
                            openai_model=st.session_state.get("kw_openai_model", "gpt-5-mini"),
                            context_hint=st.session_state.get("kw_context_hint", ""),
                        )
                    progress.progress(0.45, text="Building batch rows")
                    st.session_state["kw_output_rows"] = []
                    for path in (DEFAULT_KEYWORD_INPUT_PATH, DEFAULT_KEYWORD_OUTPUT_PATH):
                        try:
                            if path.exists():
                                path.unlink()
                        except OSError:
                            pass
                    batch_rows, stats = build_batch_rows(
                        st.session_state["keyword_rows"],
                        drop_missing=st.session_state.get("kw_drop_missing", False),
                    )
                    st.session_state["kw_batch_rows"] = batch_rows
                    st.session_state["kw_batch_stats"] = stats
                    progress.progress(0.75, text="Saving batch CSV")
                    input_path = Path(
                        st.session_state.get("kw_input_path") or str(DEFAULT_KEYWORD_INPUT_PATH)
                    )
                    if st.session_state.get("kw_save_batch_csv", True):
                        try:
                            write_csv(
                                input_path,
                                st.session_state["kw_batch_rows"],
                                ["Recipe Name", "Pinterest URL", "Recipe URL"],
                            )
                            progress.progress(1.0, text="Step 1 complete")
                            status.update(label="Step 1 complete", state="complete")
                            st.success(
                                f"Researched {len(st.session_state['keyword_rows'])} keyword rows "
                                f"({stats['with_url']} with recipe URLs). "
                                f"Built {len(st.session_state['kw_batch_rows'])} batch rows and saved to {input_path}. "
                                f"Rows without URLs can still run in keyword-only AI mode."
                            )
                        except Exception as exc:
                            status.update(label="Step 1 finished with warnings", state="complete")
                            st.warning(
                                f"Researched {len(st.session_state['keyword_rows'])} keyword rows and built "
                                f"{len(st.session_state['kw_batch_rows'])} batch rows, "
                                f"but failed to save CSV: {exc}"
                            )
                    else:
                        progress.progress(1.0, text="Step 1 complete")
                        status.update(label="Step 1 complete", state="complete")
                        st.success(
                            f"Researched {len(st.session_state['keyword_rows'])} keyword rows "
                            f"({stats['with_url']} with recipe URLs). "
                            f"Built {len(st.session_state['kw_batch_rows'])} batch rows. "
                            f"Rows without URLs can still run in keyword-only AI mode."
                        )
            except Exception as exc:
                step_one_status = "error"
                st.error(str(exc))
            finally:
                st.session_state["kw_last_step_one"] = {
                    "completed_at": step_one_started,
                    "duration": time.perf_counter() - step_one_start,
                    "status": step_one_status,
                }
                refresh_progress_panel()

            if step_one_status == "success" and st.session_state["kw_batch_rows"]:
                st.session_state["kw_active_run"] = "step2"
                refresh_run_panel(active_override="step2")
                step_two_started = datetime.now()
                step_two_start = time.perf_counter()
                step_two_status = "success"
                try:
                    output_path_input = st.session_state.get("kw_output_path") or str(
                        DEFAULT_KEYWORD_OUTPUT_PATH
                    )
                    if not output_path_input.strip():
                        output_path_input = str(DEFAULT_KEYWORD_OUTPUT_PATH)
                    output_path = Path(output_path_input)
                    log_level = st.session_state.get("kw_log_level", "INFO")
                    overwrite_output = st.session_state.get("kw_overwrite_output", True)
                    use_live_input = st.session_state.get("kw_use_live_input", True)

                    sheet_url = st.session_state.get("sheet_url", "")
                    sheet_credentials_path = st.session_state.get("sheet_credentials_path", "")
                    sheet_tab = st.session_state.get("sheet_tab", "")
                    sheet_ready_value = st.session_state.get("sheet_ready_value", "")

                    if output_path.is_dir() or str(output_path) == ".":
                        step_two_status = "error"
                        st.error("Output path must be a file, not a directory. Please specify a CSV filename.")
                    else:
                        can_run = True
                        if sheet_url and not sheet_credentials_path:
                            st.error("Google Sheet URL provided but credentials JSON is missing.")
                            can_run = False
                        if not overwrite_output and output_path.exists():
                            st.warning(
                                "Output file already exists. Results will be appended, which can mix older runs "
                                "with the current batch. Enable overwrite to keep only the latest results."
                            )
                        if overwrite_output and output_path.exists():
                            try:
                                output_path.unlink()
                            except OSError as exc:
                                step_two_status = "error"
                                st.error(f"Failed to remove existing output: {exc}")

                        temp_dir = None
                        input_path = Path(
                            st.session_state.get("kw_input_path") or str(DEFAULT_KEYWORD_INPUT_PATH)
                        )
                        run_input = input_path
                        if use_live_input:
                            try:
                                temp_dir = tempfile.TemporaryDirectory()
                                run_input = Path(temp_dir.name) / "batch_input.csv"
                                write_csv(
                                    run_input,
                                    st.session_state["kw_batch_rows"],
                                    ["Recipe Name", "Pinterest URL", "Recipe URL"],
                                )
                            except Exception as exc:
                                step_two_status = "error"
                                st.error(f"Failed to prepare live input: {exc}")
                                can_run = False
                        elif not input_path.exists():
                            step_two_status = "error"
                            st.error("Batch input file not found. Save Step 1 or enable live input.")
                            can_run = False

                        if can_run and run_input.exists():
                            log_placeholder = st.empty()
                            with st.status("Step 2: Run generator", expanded=True) as status:
                                progress = st.progress(0.0, text="Starting generator")
                                returncode, combined_log = run_generator_stream(
                                    run_input,
                                    output_path,
                                    log_level,
                                    log_placeholder=log_placeholder,
                                    progress_placeholder=progress,
                                    total_targets=len(st.session_state["kw_batch_rows"]),
                                    allow_missing_url=True,
                                    sheet_url=sheet_url,
                                    sheet_tab=sheet_tab,
                                    sheet_credentials=sheet_credentials_path,
                                    sheet_ready_value=sheet_ready_value,
                                )
                                st.session_state["kw_generator_log"] = combined_log
                                if returncode != 0:
                                    step_two_status = "error"
                                    status.update(label="Generator failed", state="error")
                                    st.error("Generator failed. Check logs for details.")
                                else:
                                    status.update(label="Generator finished", state="complete")
                                    st.success("Generator finished.")
                                if output_path.exists():
                                    try:
                                        st.session_state["kw_output_rows"] = read_csv_rows(output_path)
                                    except Exception as exc:
                                        step_two_status = "error"
                                        st.error(f"Failed to read output CSV: {exc}")
                        if temp_dir is not None:
                            temp_dir.cleanup()
                except Exception as exc:
                    step_two_status = "error"
                    st.error(str(exc))
                finally:
                    st.session_state["kw_last_step_two"] = {
                        "completed_at": step_two_started,
                        "duration": time.perf_counter() - step_two_start,
                        "status": step_two_status,
                    }
                    st.session_state["kw_active_run"] = ""
                    refresh_run_panel(active_override="")
                    refresh_progress_panel()
            else:
                if step_one_status == "success" and not st.session_state["kw_batch_rows"]:
                    st.warning(
                        "No valid batch rows were built. Add clearer keywords or disable the strict filter."
                    )
                st.session_state["kw_active_run"] = ""
                refresh_run_panel(active_override="")
                refresh_progress_panel()

        with st.expander("Advanced settings", expanded=False):
            st.markdown("**Research**")
            st.text_input(
                "OpenAI model",
                value="gpt-5-mini",
                key="kw_openai_model",
                disabled=not kw_use_openai,
            )
            st.number_input(
                "Keyword research timeout (seconds)",
                min_value=5.0,
                max_value=60.0,
                value=20.0,
                key="kw_keyword_timeout",
            )
            st.number_input(
                "Max search results per keyword",
                min_value=1,
                max_value=12,
                value=6,
                key="kw_max_results",
            )
            st.text_input(
                "Keyword context hint (optional)",
                key="kw_context_hint",
                help="Example: for dogs, keto, vegan, gluten free. Appended to each research query.",
            )

            st.markdown("**Batch & Output**")
            st.text_input(
                "Batch input path",
                key="kw_input_path",
                value=str(DEFAULT_KEYWORD_INPUT_PATH),
            )
            st.checkbox("Save batch CSV to path", value=True, key="kw_save_batch_csv")
            st.text_input(
                "Output CSV path",
                key="kw_output_path",
                value=str(DEFAULT_KEYWORD_OUTPUT_PATH),
            )
            st.selectbox(
                "Log level",
                ["INFO", "DEBUG", "WARNING", "ERROR"],
                index=0,
                key="kw_log_level",
            )
            st.checkbox("Overwrite output before run", value=True, key="kw_overwrite_output")
            st.checkbox("Use live batch data (no save needed)", value=True, key="kw_use_live_input")

            st.markdown("**Midjourney Session (optional)**")
            st.caption(
                "If the Midjourney browser is stuck or showing about:blank, reset the session. "
                "Close any Midjourney/Playwright windows first."
            )
            current_session_id = os.getenv("MIDJOURNEY_SESSION_ID", "")
            if current_session_id:
                st.caption(f"Current session: `{current_session_id}`")
            if st.button("Reset Midjourney session", key="kw_reset_midjourney"):
                result = reset_midjourney_session()
                if result["errors"]:
                    st.error("Reset completed with errors:\n" + "\n".join(result["errors"]))
                else:
                    st.success("Midjourney session reset.")
                if result["removed"]:
                    st.info("Removed session data:\n" + "\n".join(result["removed"]))
                st.info(f"New session: `{result['new_session_id']}`")

        if st.session_state["kw_generator_log"]:
            with st.expander("Generator logs", expanded=False):
                st.caption(f"Showing the last {LOG_TAIL_LIMIT} lines from the most recent run.")
                st.code(st.session_state["kw_generator_log"])

        with st.expander("Data preview", expanded=False):
            if st.session_state["keyword_rows"]:
                total_rows = len(st.session_state["keyword_rows"])
                with_urls = sum(
                    1
                    for row in st.session_state["keyword_rows"]
                    if (row.get("visit_site_url") or "").strip()
                )
                missing_urls = total_rows - with_urls
                if with_urls == 0:
                    st.info(
                        "No external recipe URLs were found from keyword research. "
                        "Step 2 can still run in keyword-only AI mode."
                    )
                elif missing_urls > 0:
                    st.info(
                        f"{missing_urls} of {total_rows} keyword rows are missing recipe URLs. "
                        "Those rows will still run in keyword-only AI mode."
                    )
                display_rows = [
                    {
                        "recipe": row.get("recipe", ""),
                        "keywords": row.get("keywords", ""),
                        "visit_site_url": row.get("visit_site_url", ""),
                        "research_source": row.get("research_source", ""),
                        "search_query": row.get("search_query", ""),
                    }
                    for row in st.session_state["keyword_rows"]
                ]
                safe_dataframe(display_rows, use_container_width=True)

            if st.session_state.get("kw_batch_stats"):
                render_keyword_batch_stats(st.session_state["kw_batch_stats"])

            if st.session_state["kw_batch_rows"]:
                safe_dataframe(st.session_state["kw_batch_rows"], use_container_width=True)

        with st.expander("Exports", expanded=False):
            if st.session_state["kw_batch_rows"]:
                csv_data = rows_to_csv(
                    st.session_state["kw_batch_rows"],
                    ["Recipe Name", "Pinterest URL", "Recipe URL"],
                )
                st.download_button(
                    "Download batch CSV",
                    data=csv_data,
                    file_name="keywords_batch_input.csv",
                    mime="text/csv",
                    key="kw_download_batch_csv",
                )

        st.markdown('<div class="section-title">Results</div>', unsafe_allow_html=True)
        if st.session_state["kw_output_rows"]:
            safe_dataframe(st.session_state["kw_output_rows"], use_container_width=True)
        elif st.session_state["kw_batch_rows"]:
            safe_dataframe(st.session_state["kw_batch_rows"], use_container_width=True)
        else:
            st.info("Run the engine to see results.")


def main() -> None:
    st.set_page_config(page_title="Recipe Pipeline UI", layout="wide")
    pages = [
        st.Page(render_pins_page, title="Pins", default=True),
        st.Page(render_keywords_page, title="Keywords", url_path="keywords"),
    ]
    navigation = st.navigation(pages, position="sidebar")
    navigation.run()


if __name__ == "__main__":
    main()
