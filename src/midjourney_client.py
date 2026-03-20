import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

from .config import Settings
from .midjourney_prompt_sanitizer import sanitize_midjourney_prompt
from .prompts.types import PROMPT_TYPE_ORDER


MIDJOURNEY_URL_RE = re.compile(r"https?://cdn\.midjourney\.com/[^\s\"']+", re.IGNORECASE)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_path(value: str, base: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return path


def _read_urls(path: Path) -> List[str]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return []
    urls: List[str] = []
    for line in content.splitlines():
        match = MIDJOURNEY_URL_RE.search(line)
        if match:
            urls.append(match.group(0))
            continue
        cleaned = line.strip()
        if cleaned.startswith("http"):
            urls.append(cleaned)
    return urls


def _read_new_lines(path: Path, offset: int) -> tuple[List[str], int]:
    if not path.exists():
        return [], offset
    with path.open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        data = handle.read()
        new_offset = handle.tell()
    lines = [line for line in data.splitlines() if line.strip()]
    return lines, new_offset


def _tail_file(path: Path, max_lines: int = 80) -> str:
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    lines = [line for line in content.splitlines() if line.strip()]
    if not lines:
        return ""
    tail = lines[-max_lines:]
    return "\n".join(tail)


class MidjourneyQueueRunner:
    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self._settings = settings
        self._logger = logger
        self._base = _repo_root()
        self._worker_path = _resolve_path(settings.midjourney_worker_path, self._base)
        if not self._worker_path.exists():
            raise FileNotFoundError(f"Midjourney worker not found: {self._worker_path}")
        if not _has_midjourney_auth(settings, self._base):
            raise RuntimeError("Midjourney credentials not configured")

        self._temp_dir = tempfile.TemporaryDirectory()
        temp_path = Path(self._temp_dir.name)
        self._queue_file = temp_path / "queue.txt"
        self._done_file = temp_path / "done.txt"
        self._failed_file = temp_path / "failed.txt"
        self._log_file = temp_path / "worker.log"
        self._log_handle = self._log_file.open("a", encoding="utf-8")
        self._queue_file.write_text("", encoding="utf-8")
        self._done_file.write_text("", encoding="utf-8")
        self._failed_file.write_text("", encoding="utf-8")
        self._done_offset = 0
        self._failed_offset = 0
        self._done_backlog: List[str] = []
        self._failed_backlog: List[str] = []

        cmd = [
            sys.executable,
            str(self._worker_path),
            "--watch-queue",
            "--keep-browser-open",
            "--queue-file",
            str(self._queue_file),
            "--done-file",
            str(self._done_file),
            "--failed-file",
            str(self._failed_file),
            "--poll-seconds",
            str(settings.midjourney_queue_poll_seconds),
            "--exit-when-queue-empty",
            "--empty-queue-exit-seconds",
            str(settings.midjourney_queue_exit_seconds),
            "--timeout-seconds",
            str(settings.midjourney_timeout_seconds),
        ]
        if settings.midjourney_headless:
            cmd.append("--headless")
        if settings.midjourney_auto_fallback_headful:
            cmd.append("--auto-fallback-headful")
        profile_dir, storage_state, cookies_file = _resolve_session_paths(settings, self._base)
        if profile_dir:
            cmd.extend(["--profile-dir", str(profile_dir)])
        if cookies_file:
            cmd.extend(["--cookies-file", str(cookies_file)])
        if storage_state:
            cmd.extend(["--storage-state", str(storage_state)])

        self._process = subprocess.Popen(
            cmd,
            cwd=self._base,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
        )
        self._logger.info("Midjourney worker log: %s", self._log_file)

    def close(self) -> None:
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        if getattr(self, "_log_handle", None):
            try:
                self._log_handle.close()
            except Exception:
                pass
        if self._temp_dir:
            self._temp_dir.cleanup()

    def _append_prompt(self, prompt: str) -> None:
        with self._queue_file.open("a", encoding="utf-8") as handle:
            handle.write(f"{prompt}\n")

    def _poll_backlog(self) -> None:
        lines, self._done_offset = _read_new_lines(self._done_file, self._done_offset)
        if lines:
            self._done_backlog.extend(lines)
        lines, self._failed_offset = _read_new_lines(self._failed_file, self._failed_offset)
        if lines:
            self._failed_backlog.extend(lines)

    def _next_done_line(self) -> Optional[str]:
        if self._done_backlog:
            return self._done_backlog.pop(0)
        return None

    def _next_failed_line(self) -> Optional[str]:
        if self._failed_backlog:
            return self._failed_backlog.pop(0)
        return None

    def submit(self, prompt: str) -> str:
        self._append_prompt(prompt)
        deadline = time.time() + max(10, self._settings.midjourney_timeout_seconds)
        while time.time() < deadline:
            if self._process.poll() is not None:
                tail = _tail_file(self._log_file)
                if tail:
                    raise RuntimeError(
                        "Midjourney worker exited unexpectedly. "
                        "Last log lines:\n" + tail
                    )
                raise RuntimeError("Midjourney worker exited unexpectedly")
            self._poll_backlog()
            failed_line = self._next_failed_line()
            if failed_line:
                tail = _tail_file(self._log_file)
                if tail:
                    raise RuntimeError(f"Midjourney failed: {failed_line}\n{tail}")
                raise RuntimeError(f"Midjourney failed: {failed_line}")
            done_line = self._next_done_line()
            if done_line:
                parts = done_line.split("\t", 1)
                if len(parts) == 2:
                    return parts[1].strip()
                return ""
            time.sleep(1)
        raise TimeoutError("Timed out waiting for Midjourney image URL")


def _sessionize_file(path: Path, session_id: str) -> Path:
    if path.suffix:
        return path.with_name(f"{path.stem}-{session_id}{path.suffix}")
    return Path(f"{path}-{session_id}")


def _resolve_session_paths(
    settings: Settings, base: Path
) -> tuple[Path, Optional[Path], Optional[Path]]:
    profile_dir = _resolve_path(settings.midjourney_profile_dir, base)
    storage_state = (
        _resolve_path(settings.midjourney_storage_state, base)
        if settings.midjourney_storage_state
        else None
    )
    cookies_file = (
        _resolve_path(settings.midjourney_cookies_file, base)
        if settings.midjourney_cookies_file
        else None
    )

    session_id = (settings.midjourney_session_id or "").strip()
    if session_id:
        profile_dir = profile_dir / session_id
        if storage_state is not None:
            storage_state = _sessionize_file(storage_state, session_id)

    return profile_dir, storage_state, cookies_file


def _has_midjourney_auth(settings: Settings, base: Path) -> bool:
    if os.getenv("DISCORD_EMAIL") and os.getenv("DISCORD_PASSWORD"):
        return True
    _, storage_state, cookies_file = _resolve_session_paths(settings, base)
    for candidate in [cookies_file, storage_state]:
        if candidate and candidate.exists():
            return True
    return False


def generate_midjourney_images(
    prompts: Dict[str, str],
    settings: Settings,
    logger: logging.Logger,
) -> Dict[str, str]:
    ordered_keys = list(PROMPT_TYPE_ORDER)
    results = {key: "" for key in ordered_keys}

    prompt_list: List[str] = []
    prompt_keys: List[str] = []
    for key in ordered_keys:
        prompt = (prompts.get(key) or "").strip()
        if not prompt:
            continue
        prompt_list.append(sanitize_midjourney_prompt(prompt, key))
        prompt_keys.append(key)

    if not prompt_list:
        return results

    base = _repo_root()
    worker_path = _resolve_path(settings.midjourney_worker_path, base)
    if not worker_path.exists():
        logger.warning("Midjourney worker not found: %s", worker_path)
        return results

    if not _has_midjourney_auth(settings, base):
        logger.warning("Midjourney credentials not configured; skipping image generation")
        return results

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as handle:
        output_path = Path(handle.name)

    cmd = [sys.executable, str(worker_path)]
    for prompt in prompt_list:
        cmd.extend(["--prompt", prompt])
    cmd.extend(["--output-file", str(output_path)])
    cmd.extend(["--timeout-seconds", str(settings.midjourney_timeout_seconds)])

    if settings.midjourney_headless:
        cmd.append("--headless")
    if settings.midjourney_auto_fallback_headful:
        cmd.append("--auto-fallback-headful")
    profile_dir, storage_state, cookies_file = _resolve_session_paths(settings, base)
    if profile_dir:
        cmd.extend(["--profile-dir", str(profile_dir)])
    if cookies_file:
        cmd.extend(["--cookies-file", str(cookies_file)])
    if storage_state:
        cmd.extend(["--storage-state", str(storage_state)])

    run = subprocess.run(cmd, capture_output=True, text=True, cwd=base)
    urls = _read_urls(output_path)
    if not urls:
        urls = MIDJOURNEY_URL_RE.findall(run.stdout or "")

    if run.returncode != 0:
        message = (run.stderr or run.stdout or "").strip()
        if message:
            logger.warning("Midjourney worker failed: %s", message)
        else:
            logger.warning("Midjourney worker failed with exit code %s", run.returncode)

    for key, url in zip(prompt_keys, urls):
        results[key] = url

    try:
        output_path.unlink()
    except OSError:
        pass

    return results


def generate_midjourney_images_queue(
    prompts: Dict[str, str],
    runner: MidjourneyQueueRunner,
    logger: logging.Logger,
) -> Dict[str, str]:
    ordered_keys = list(PROMPT_TYPE_ORDER)
    results = {key: "" for key in ordered_keys}
    for key in ordered_keys:
        prompt = (prompts.get(key) or "").strip()
        if not prompt:
            continue
        prompt = sanitize_midjourney_prompt(prompt, key)
        try:
            results[key] = runner.submit(prompt)
        except Exception as exc:
            logger.warning("Midjourney queue failed for %s: %s", key, exc)
            results[key] = ""
    return results
