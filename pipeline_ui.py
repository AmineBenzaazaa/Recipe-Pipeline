#!/usr/bin/env python3
import csv
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

import streamlit as st


APP_DIR = Path(__file__).resolve().parent
PIN_EXTRACT_PATH = APP_DIR / "pin_extract.py"
GENERATOR_PATH = APP_DIR / "generate_recipe_batch.py"
DEFAULT_PINS_PATH = APP_DIR / "pins.txt"
DEFAULT_INPUT_PATH = APP_DIR / "batch_input.csv"
DEFAULT_OUTPUT_PATH = APP_DIR / "batch_output.csv"


def load_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError:
        return ""


def run_pin_extract(
    pins_text: str,
    timeout: float,
    use_openai: bool,
    openai_model: str,
) -> List[Dict[str, str]]:
    if not pins_text.strip():
        return []

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as handle:
        handle.write(pins_text)
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


def run_generator(input_path: Path, output_path: Path, log_level: str) -> subprocess.CompletedProcess:
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
    return subprocess.run(cmd, capture_output=True, text=True)


def render_progress(step_one: bool, step_two: bool, output_ready: bool) -> None:
    def dot(active: bool) -> str:
        color = "#2a6f5e" if active else "#c9b9a9"
        return f'<span class="rail-dot" style="background:{color};"></span>'

    html = f"""
    <div class="rail">
      <div class="rail-title">Pipeline Status</div>
      <div class="rail-item">{dot(step_one)} Step 1 ready</div>
      <div class="rail-item">{dot(step_two)} Step 2 prepared</div>
      <div class="rail-item">{dot(output_ready)} Final table ready</div>
      <div class="rail-note">Use the right panel to run each step.</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


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


def main() -> None:
    st.set_page_config(page_title="Recipe Pipeline UI", layout="wide")
    inject_styles()

    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">Recipe Pipeline</div>
          <div class="hero-title">Pin to Recipe System</div>
          <p class="hero-copy">
            Step 1 extracts recipe titles and visit links from Pinterest pins.
            Step 2 prepares the batch file for the main generator and can run it.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "pins_text" not in st.session_state:
        st.session_state["pins_text"] = load_text_file(DEFAULT_PINS_PATH)
    if "pin_rows" not in st.session_state:
        st.session_state["pin_rows"] = []
    if "batch_rows" not in st.session_state:
        st.session_state["batch_rows"] = []
    if "output_rows" not in st.session_state:
        st.session_state["output_rows"] = []

    step_one_ready = bool(st.session_state["pin_rows"])
    step_two_ready = bool(st.session_state["batch_rows"])
    output_ready = bool(st.session_state["output_rows"])

    left, right = st.columns([1, 3], gap="large")
    with left:
        render_progress(step_one_ready, step_two_ready, output_ready)

    with right:
        st.markdown('<div class="section-title">Step 1: Pin Extract</div>', unsafe_allow_html=True)
        st.caption("Paste pins, upload a file, or load pins.txt to start.")

        pins_col, options_col = st.columns([3, 2], gap="large")
        with pins_col:
            st.text_area("Pins input", key="pins_text", height=220)
        with options_col:
            if st.button("Load pins.txt"):
                st.session_state["pins_text"] = load_text_file(DEFAULT_PINS_PATH)

            uploaded = st.file_uploader("Upload pin list", type=["txt"])
            if uploaded:
                st.session_state["pins_text"] = uploaded.read().decode("utf-8", errors="ignore")

            use_openai = st.checkbox("Use OpenAI (optional)", value=True)
            openai_model = st.text_input(
                "OpenAI model",
                value="gpt-3.5-turbo",
                disabled=not use_openai,
            )
            timeout = st.number_input("Pin timeout (seconds)", min_value=5.0, max_value=60.0, value=20.0)

        if st.button("Run Step 1"):
            try:
                st.session_state["pin_rows"] = run_pin_extract(
                    st.session_state["pins_text"],
                    timeout=timeout,
                    use_openai=use_openai,
                    openai_model=openai_model,
                )
                # Reset downstream steps when new pins are extracted.
                st.session_state["batch_rows"] = []
                st.session_state["output_rows"] = []
                st.success(f"Extracted {len(st.session_state['pin_rows'])} pins.")
            except Exception as exc:
                st.error(str(exc))

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
            st.dataframe(display_rows, use_container_width=True)

        st.markdown('<div class="section-title">Step 2: Main System Input</div>', unsafe_allow_html=True)
        st.caption("Build the batch input file that the recipe generator expects.")

        drop_missing = st.checkbox(
            "Only keep rows with Recipe Name and Recipe URL",
            value=False,
            help="Rows missing a visit URL will be excluded. Uncheck to include all rows (but pipeline will only process rows with URLs).",
        )
        if st.button("Build batch table"):
            batch_rows, stats = build_batch_rows(
                st.session_state["pin_rows"],
                drop_missing=drop_missing,
            )
            st.session_state["batch_rows"] = batch_rows
            # Clear output when batch input changes.
            st.session_state["output_rows"] = []
            
            # Show statistics
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

        if st.session_state["batch_rows"]:
            st.dataframe(st.session_state["batch_rows"], use_container_width=True)

        input_path = Path(
            st.text_input("Batch input path (optional)", value=str(DEFAULT_INPUT_PATH))
        )
        if st.button("Save batch CSV"):
            try:
                write_csv(
                    input_path,
                    st.session_state["batch_rows"],
                    ["Recipe Name", "Pinterest URL", "Recipe URL"],
                )
                st.success(f"Saved {len(st.session_state['batch_rows'])} rows to {input_path}.")
            except Exception as exc:
                st.error(str(exc))

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

        st.markdown('<div class="section-title">Run Step 2 (Optional)</div>', unsafe_allow_html=True)
        st.caption("Run the main generator if your API keys are configured.")

        output_path_input = st.text_input("Output CSV path", value=str(DEFAULT_OUTPUT_PATH))
        if not output_path_input or output_path_input.strip() == "":
            output_path_input = str(DEFAULT_OUTPUT_PATH)
        output_path = Path(output_path_input)
        log_level = st.selectbox("Log level", ["INFO", "DEBUG", "WARNING", "ERROR"], index=0)
        overwrite_output = st.checkbox("Overwrite output before run", value=True)
        use_live_input = st.checkbox("Use live batch data (no save needed)", value=True)

        if st.button("Run generator"):
            if not st.session_state["batch_rows"]:
                st.error("Build the batch table first.")
            elif output_path.is_dir() or str(output_path) == ".":
                st.error("Output path must be a file, not a directory. Please specify a CSV filename.")
            else:
                if not overwrite_output and output_path.exists():
                    st.warning(
                        "Output file already exists. Results will be appended, which can mix older runs "
                        "with the current batch. Enable overwrite to keep only the latest results."
                    )
                if overwrite_output and output_path.exists():
                    try:
                        output_path.unlink()
                    except OSError as exc:
                        st.error(f"Failed to remove existing output: {exc}")
                temp_dir = None
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
                        st.error(f"Failed to prepare live input: {exc}")
                elif not input_path.exists():
                    st.error("Batch input file not found. Save Step 2 or enable live input.")
                if run_input.exists():
                    result = run_generator(run_input, output_path, log_level)
                    if result.returncode != 0:
                        st.error(result.stderr.strip() or "Generator failed.")
                    else:
                        st.success("Generator finished.")
                    if output_path.exists():
                        try:
                            st.session_state["output_rows"] = read_csv_rows(output_path)
                        except Exception as exc:
                            st.error(f"Failed to read output CSV: {exc}")
                if temp_dir is not None:
                    temp_dir.cleanup()

        st.markdown('<div class="section-title">Final Table</div>', unsafe_allow_html=True)
        if st.session_state["output_rows"]:
            st.dataframe(st.session_state["output_rows"], use_container_width=True)
        elif st.session_state["batch_rows"]:
            st.dataframe(st.session_state["batch_rows"], use_container_width=True)
        else:
            st.info("Run Step 1 and Step 2 to see the final table.")


if __name__ == "__main__":
    main()
