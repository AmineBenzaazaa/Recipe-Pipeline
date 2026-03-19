import argparse
import json
import os
import sys
import time
from typing import List, Optional, Set
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


DEFAULT_PROFILE_DIR = ".playwright/discord-profile"
DEFAULT_COOKIES_PATH = "midjourney_cookies.json"
DEFAULT_STORAGE_STATE_PATH = ".playwright/midjourney_storage_state.json"
DEFAULT_QUEUE_FILE = "prompts_queue.txt"
DEFAULT_DONE_FILE = "prompts_done.txt"
DEFAULT_FAILED_FILE = "prompts_failed.txt"


class CloudflareChallengeError(RuntimeError):
    pass


def _load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        # Best-effort load; env vars can still be provided by the shell.
        pass


def _read_queue_file(path: str) -> List[str]:
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = []
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                lines.append(line)
            return lines
    except Exception:
        return []


def _write_queue_file(path: str, prompts: List[str]) -> None:
    if not path:
        return
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        for line in prompts:
            handle.write(f"{line}\n")
    os.replace(tmp_path, path)


def _append_line(path: str, line: str) -> None:
    if not path:
        return
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _maybe_login(page, email: str, password: str) -> None:
    try:
        email_input = page.locator('input[name="email"]')
        email_input.wait_for(state="visible", timeout=6000)
    except PlaywrightTimeoutError:
        return

    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')


def _maybe_handle_2fa(page) -> None:
    selectors = [
        'input[name="code"]',
        'input[autocomplete="one-time-code"]',
    ]
    for selector in selectors:
        try:
            otp_input = page.locator(selector)
            otp_input.wait_for(state="visible", timeout=6000)
            code = input("Enter Discord 2FA code: ").strip()
            if not code:
                raise ValueError("2FA code is required to continue.")
            otp_input.fill(code)
            page.keyboard.press("Enter")
            return
        except PlaywrightTimeoutError:
            continue


def _login_midjourney_with_discord(page, timeout_ms: int) -> None:
    print("[midjourney] opening homepage")
    page.goto("https://www.midjourney.com", wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PlaywrightTimeoutError:
        print("[midjourney] network idle timeout, continuing")
    if _is_midjourney_logged_in(page, 1500):
        print("[midjourney] already logged in on homepage")
        return
    log_in_timeout = min(timeout_ms, 2000)
    try:
        log_in = page.get_by_role("button", name="Log In")
        log_in.first.wait_for(state="visible", timeout=log_in_timeout)
        log_in.first.click()
        print("[midjourney] clicked Log In by role")
    except PlaywrightTimeoutError:
        try:
            log_in = page.locator('button:has-text("Log In")')
            log_in.first.wait_for(state="visible", timeout=log_in_timeout)
            log_in.first.click()
            print("[midjourney] clicked Log In by text (case)")
        except PlaywrightTimeoutError:
            try:
                log_in = page.locator('button span:has-text("Log In")').locator("..")
                log_in.first.wait_for(state="visible", timeout=log_in_timeout)
                log_in.first.click()
                print("[midjourney] clicked Log In by span parent")
            except PlaywrightTimeoutError:
                print("[midjourney] Log In button not found, trying JS click")
                clicked = page.evaluate(
                    """
                    () => {
                      const buttons = Array.from(document.querySelectorAll("button"));
                      const target = buttons.find((btn) => {
                        const text = (btn.innerText || "").trim();
                        return text === "Log In";
                      });
                      if (target) {
                        target.click();
                        return true;
                      }
                      return false;
                    }
                    """
                )
                if clicked:
                    print("[midjourney] clicked Log In via JS")
                else:
                    try:
                        page.click('button:has-text("Log In")', force=True, timeout=3000)
                        print("[midjourney] clicked Log In via forced click")
                    except PlaywrightTimeoutError:
                        print("[midjourney] Log In button not found")
                        try:
                            button_texts = page.evaluate(
                                """
                                () => Array.from(document.querySelectorAll("button"))
                                  .map((btn) => (btn.innerText || "").trim())
                                  .filter(Boolean)
                                  .slice(0, 20)
                                """
                            )
                            print(f"[midjourney] visible buttons: {button_texts}")
                        except Exception:
                            pass
                        try:
                            page.screenshot(path="midjourney_debug.png", full_page=True)
                            print("[midjourney] saved screenshot to midjourney_debug.png")
                        except Exception:
                            pass
                    return

    try:
        discord_button = page.locator('text=Continue with Discord')
        discord_button.first.wait_for(state="visible", timeout=6000)
        with page.expect_popup() as popup_info:
            discord_button.first.click()
        print("[midjourney] clicked Continue with Discord")
        popup = popup_info.value
        try:
            authorize = popup.locator('button:has-text("Authorize")')
            authorize.wait_for(state="visible", timeout=timeout_ms)
            authorize.click()
            print("[midjourney] authorized Discord app")
        except PlaywrightTimeoutError:
            print("[midjourney] authorize button not found")
            pass
        try:
            popup.close()
        except Exception:
            pass
    except PlaywrightTimeoutError:
        print("[midjourney] Continue with Discord not found")
        return


def _is_cloudflare_challenge(page) -> bool:
    try:
        return page.evaluate(
            """
            () => {
                const text = (document.body && document.body.innerText || "").toLowerCase();
                if (text.includes("verify you are human") || text.includes("cloudflare")) {
                    return true;
                }
                const turnstile =
                    document.querySelector("iframe[src*='challenges.cloudflare.com']") ||
                    document.querySelector("iframe[src*='turnstile']") ||
                    document.querySelector("input[name='cf-turnstile-response']");
                return !!turnstile;
            }
            """
        )
    except Exception:
        return False


def _ensure_midjourney_logged_in(
    page,
    email: str,
    password: str,
    timeout_seconds: int,
    allow_manual: bool,
    raise_on_cloudflare: bool,
) -> bool:
    page.goto("https://www.midjourney.com/imagine", wait_until="domcontentloaded")
    if _is_midjourney_logged_in(page, 2000):
        print("[midjourney] session is logged in")
        return True

    print("[midjourney] session not logged in yet; logging in via Discord")
    page.goto("https://discord.com/login", wait_until="domcontentloaded")
    _maybe_login(page, email, password)
    _maybe_handle_2fa(page)

    _login_midjourney_with_discord(page, timeout_seconds * 1000)
    page.goto("https://www.midjourney.com/imagine", wait_until="domcontentloaded")
    if _is_midjourney_logged_in(page, 5000):
        print("[midjourney] session is logged in")
        return True

    if allow_manual:
        print("[midjourney] manual verification may be required (Cloudflare/2FA)")
        input("Complete verification in the browser, then press Enter to continue...")
        page.goto("https://www.midjourney.com/imagine", wait_until="domcontentloaded")
        if _is_midjourney_logged_in(page, 5000):
            print("[midjourney] session is logged in")
            return True

    if _is_cloudflare_challenge(page):
        print("[midjourney] Cloudflare verification detected")
        if raise_on_cloudflare:
            raise CloudflareChallengeError(
                "Cloudflare verification required; headless login blocked."
            )

    print("[midjourney] session not logged in yet")
    return False


def _click_create(page, timeout_ms: int) -> None:
    def _attempt_click(locator, label: str) -> bool:
        try:
            locator.first.wait_for(state="attached", timeout=timeout_ms)
            try:
                locator.first.scroll_into_view_if_needed(timeout=timeout_ms)
            except PlaywrightTimeoutError:
                pass
            try:
                locator.first.hover(timeout=min(timeout_ms, 1500), force=True)
                time.sleep(0.1)
            except PlaywrightTimeoutError:
                pass
            locator.first.click(timeout=timeout_ms, force=True)
            print(f"[midjourney] clicked Create ({label})")
            return True
        except PlaywrightTimeoutError:
            return False
        except Exception:
            return False

    def _nudge_sidebar() -> None:
        try:
            size = page.viewport_size
            if not size:
                size = page.evaluate(
                    "() => ({ w: window.innerWidth, h: window.innerHeight })"
                )
            page.mouse.move(5, int(size["h"] / 2))
            time.sleep(0.2)
        except Exception:
            pass

    if _attempt_click(page.get_by_role("button", name="Create"), "role"):
        return
    if _attempt_click(page.locator('text=Create'), "text"):
        return

    icon = page.locator("svg g#Create")
    icon_parent = icon.locator(
        "xpath=ancestor::*[self::button or @role='button' or self::a][1]"
    )
    if _attempt_click(icon_parent, "icon parent"):
        return
    if _attempt_click(icon.locator(".."), "icon svg"):
        return
    if _attempt_click(icon, "icon"):
        return

    _nudge_sidebar()
    if _attempt_click(icon_parent, "icon parent after hover"):
        return

    print("[midjourney] Create icon not clickable, trying closest clickable parent")
    clicked = page.evaluate(
        """
        () => {
          const icon = document.querySelector("svg g#Create");
          if (!icon) return false;
          const svg = icon.closest("svg");
          const target =
            icon.closest("button,[role='button'],a") ||
            (svg && svg.closest("button,[role='button'],a")) ||
            (icon.parentElement && icon.parentElement.closest("button,[role='button'],a"));
          if (target) {
            target.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
            target.click();
            return true;
          }
          const clickable = icon.closest("[onclick],button,[role='button'],a");
          if (clickable) {
            clickable.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
            clickable.click();
            return true;
          }
          return false;
        }
        """
    )
    if clicked:
        print("[midjourney] clicked Create via closest clickable parent")
        return
    print("[midjourney] Create button not found")
    return


def _is_midjourney_logged_in(page, timeout_ms: int) -> bool:
    selectors = [
        'text=Create',
        'input[placeholder*="imagine"]',
        'textarea[placeholder*="imagine"]',
    ]
    for selector in selectors:
        try:
            page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
            return True
        except PlaywrightTimeoutError:
            continue
    return False


def _fill_midjourney_prompt(page, prompt: str, timeout_ms: int) -> None:
    selectors = [
        "#desktop_input_bar",
        'input[placeholder*="imagine"]',
        'textarea[placeholder*="imagine"]',
        'input[placeholder*="Imagine"]',
        'textarea[placeholder*="Imagine"]',
    ]
    for selector in selectors:
        locator = page.locator(selector)
        try:
            locator.first.wait_for(state="visible", timeout=timeout_ms)
            locator.first.click()
            locator.first.fill(prompt)
            locator.first.press("Enter")
            print(f"[midjourney] prompt submitted via {selector}")
            return
        except PlaywrightTimeoutError:
            continue
    raise RuntimeError("Could not find the Midjourney prompt input.")


def _get_image_urls(page) -> List[str]:
    urls = page.evaluate(
        """
        () => {
            const images = Array.from(
                document.querySelectorAll('img[src*="cdn.midjourney.com"]')
            );
            return images.map((img) => img.src);
        }
        """
    )
    normalized: List[str] = []
    seen: Set[str] = set()
    for url in urls or []:
        fixed = _normalize_midjourney_url(url)
        if fixed and fixed not in seen:
            normalized.append(fixed)
            seen.add(fixed)
    return normalized


def _normalize_midjourney_url(url: str) -> str:
    if not url:
        return url
    parts = urlsplit(url)
    path = parts.path
    if path.endswith(".webp"):
        path = path[:-5] + ".png"
    query = parts.query
    if query:
        params = parse_qsl(query, keep_blank_values=True)
        changed = False
        updated: List[tuple] = []
        for key, value in params:
            lowered = key.lower()
            if lowered in ("format", "fm") and value.lower() == "webp":
                value = "png"
                changed = True
            if lowered in ("width", "height", "w", "h", "q", "quality", "fit", "auto", "dpr"):
                changed = True
                continue
            updated.append((key, value))
        if changed:
            query = urlencode(updated, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def _get_best_image_url(page, token: str) -> Optional[str]:
    return page.evaluate(
        """
        (token) => {
            const imgs = Array.from(document.querySelectorAll('img[src*="cdn.midjourney.com"]'));
            const links = Array.from(document.querySelectorAll('a[href*="cdn.midjourney.com"]'));

            const parseSrcset = (srcset) => {
                if (!srcset) return null;
                const candidates = srcset.split(",").map((item) => item.trim()).filter(Boolean);
                let best = null;
                for (const cand of candidates) {
                    const parts = cand.split(/\\s+/);
                    const url = parts[0];
                    let score = 0;
                    if (parts[1]) {
                        if (parts[1].endsWith("w")) {
                            score = parseInt(parts[1], 10) || 0;
                        } else if (parts[1].endsWith("x")) {
                            score = Math.round((parseFloat(parts[1]) || 0) * 1000);
                        }
                    }
                    if (!best || score > best.score) {
                        best = { url, score };
                    }
                }
                return best;
            };

            const pickBest = (onlyToken) => {
                let bestUrl = null;
                let bestScore = 0;
                const consider = (url, score) => {
                    if (!url) return;
                    const matches = token ? url.includes(token) : true;
                    if (onlyToken && token && !matches) return;
                    const finalScore = score + (matches ? 1 : 0);
                    if (!bestUrl || finalScore > bestScore) {
                        bestUrl = url;
                        bestScore = finalScore;
                    }
                };

                for (const img of imgs) {
                    const srcsetBest = parseSrcset(img.srcset || "");
                    const naturalArea = (img.naturalWidth || 0) * (img.naturalHeight || 0);
                    const rect = img.getBoundingClientRect();
                    const displayArea = Math.max(0, rect.width) * Math.max(0, rect.height);
                    const baseScore = naturalArea || (srcsetBest ? (srcsetBest.score * srcsetBest.score) : 0) || displayArea;

                    consider(img.currentSrc || "", baseScore);
                    consider(img.src || "", baseScore);
                    if (srcsetBest && srcsetBest.url) {
                        consider(srcsetBest.url, srcsetBest.score * srcsetBest.score || baseScore);
                    }
                }

                for (const link of links) {
                    const href = link.getAttribute("href") || "";
                    consider(href, 1);
                }

                return bestUrl;
            };

            return pickBest(true) || pickBest(false);
        }
        """,
        token,
    )


def _get_viewer_image_url(page, token: str, timeout_ms: int) -> Optional[str]:
    try:
        page.wait_for_function(
            """
            (token) => {
                const imgs = Array.from(document.querySelectorAll('img[src*="cdn.midjourney.com"]'));
                return imgs.some((img) => {
                    const src = (img.currentSrc || img.src || "");
                    if (token && !src.includes(token)) return false;
                    const rect = img.getBoundingClientRect();
                    return rect.width >= 300 && rect.height >= 300;
                });
            }
            """,
            arg=token,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        return None

    return page.evaluate(
        """
        (token) => {
            const imgs = Array.from(document.querySelectorAll('img[src*="cdn.midjourney.com"]'));
            let best = null;
            for (const img of imgs) {
                const src = img.currentSrc || img.src || "";
                if (!src) continue;
                if (token && !src.includes(token)) continue;
                const rect = img.getBoundingClientRect();
                const displayArea = Math.max(0, rect.width) * Math.max(0, rect.height);
                const naturalArea = (img.naturalWidth || 0) * (img.naturalHeight || 0);
                const score = (displayArea * 2) + naturalArea;
                if (!best || score > best.score) {
                    best = { url: src, score };
                }
            }
            return best ? best.url : null;
        }
        """,
        token,
    )


def _load_midjourney_cookies(path: str) -> List[dict]:
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read().strip()
    except Exception:
        return []
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except Exception:
        return []
    if not isinstance(items, list):
        return []

    cookies: List[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        domain = (item.get("domain") or "").strip()
        if "midjourney.com" not in domain:
            continue
        name = item.get("name")
        value = item.get("value")
        if not name or value is None:
            continue
        secure = bool(item.get("secure"))
        cookie: dict = {
            "name": name,
            "value": value,
            "httpOnly": bool(item.get("httpOnly")),
            "secure": secure,
        }

        host_only = bool(item.get("hostOnly")) or name.startswith("__Host-")
        if host_only:
            host = domain.lstrip(".")
            scheme = "https" if secure else "http"
            cookie["url"] = f"{scheme}://{host}"
        else:
            cookie["domain"] = domain
            cookie["path"] = item.get("path") or "/"
        same_site = (item.get("sameSite") or "").lower()
        if same_site in ("lax", "strict"):
            cookie["sameSite"] = same_site.capitalize()
        elif same_site in ("no_restriction", "none"):
            if secure:
                cookie["sameSite"] = "None"
        # "unspecified" -> omit

        if not item.get("session"):
            expires = item.get("expirationDate")
            if isinstance(expires, (int, float)):
                cookie["expires"] = int(expires)

        cookies.append(cookie)
    return cookies


def _click_viewer_image(page, token: str, timeout_ms: int) -> None:
    try:
        page.wait_for_function(
            """
            (token) => {
                const imgs = Array.from(document.querySelectorAll('img[src*="cdn.midjourney.com"]'));
                return imgs.some((img) => {
                    const src = img.currentSrc || img.src || "";
                    if (token && !src.includes(token)) return false;
                    const rect = img.getBoundingClientRect();
                    return rect.width >= 300 && rect.height >= 300;
                });
            }
            """,
            arg=token,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        return

    page.evaluate(
        """
        (token) => {
            const imgs = Array.from(document.querySelectorAll('img[src*="cdn.midjourney.com"]'));
            let best = null;
            for (const img of imgs) {
                const src = img.currentSrc || img.src || "";
                if (!src) continue;
                if (token && !src.includes(token)) continue;
                const rect = img.getBoundingClientRect();
                const displayArea = Math.max(0, rect.width) * Math.max(0, rect.height);
                const naturalArea = (img.naturalWidth || 0) * (img.naturalHeight || 0);
                const score = (displayArea * 2) + naturalArea;
                if (!best || score > best.score) {
                    best = { node: img, score };
                }
            }
            if (best && best.node) {
                best.node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
                return true;
            }
            return false;
        }
        """,
        token,
    )


def _midjourney_token_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = [part for part in urlsplit(url).path.split("/") if part]
    except Exception:
        return ""
    if len(parts) >= 2:
        return parts[-2]
    if parts:
        return parts[-1]
    return ""


def _open_image_viewer(page, image_url: str, timeout_ms: int) -> None:
    token = _midjourney_token_from_url(image_url)
    if not token:
        return
    locator = page.locator(f'img[src*="{token}"]')
    try:
        locator.first.wait_for(state="visible", timeout=timeout_ms)
        try:
            locator.first.scroll_into_view_if_needed(timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass
        locator.first.click(timeout=timeout_ms, force=True)
    except PlaywrightTimeoutError:
        return


def _close_image_viewer(page, timeout_ms: int) -> None:
    try:
        page.keyboard.press("Escape")
    except Exception:
        return
    try:
        page.wait_for_timeout(min(timeout_ms, 800))
    except PlaywrightTimeoutError:
        pass


def _get_full_res_image_url(page, image_url: str, timeout_ms: int) -> str:
    _open_image_viewer(page, image_url, timeout_ms)
    token = _midjourney_token_from_url(image_url)
    _click_viewer_image(page, token, timeout_ms)
    try:
        page.wait_for_function(
            """
            (token) => {
                const imgs = Array.from(document.querySelectorAll('img[src*="cdn.midjourney.com"]'));
                return imgs.some((img) => {
                    const src = (img.currentSrc || img.src || "") + " " + (img.srcset || "");
                    if (token && !src.includes(token)) return false;
                    return (img.naturalWidth || 0) >= 1000 || (img.naturalHeight || 0) >= 1000;
                });
            }
            """,
            arg=token,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        pass

    viewer_url = _get_viewer_image_url(page, token, timeout_ms)
    if viewer_url:
        _close_image_viewer(page, timeout_ms)
        return viewer_url

    best = _get_best_image_url(page, token)
    if best:
        _close_image_viewer(page, timeout_ms)
        return _normalize_midjourney_url(best)
    _close_image_viewer(page, timeout_ms)
    return _normalize_midjourney_url(image_url)


def _process_prompt(page, prompt: str, timeout_seconds: int) -> str:
    timeout_ms = timeout_seconds * 1000
    try:
        for extra in list(page.context.pages):
            if extra == page:
                continue
            url = (extra.url or "").strip().lower()
            if not url or url == "about:blank":
                try:
                    extra.close()
                except Exception:
                    pass
    except Exception:
        pass
    _close_image_viewer(page, timeout_ms)
    existing_urls = set(_get_image_urls(page))
    _fill_midjourney_prompt(page, prompt, timeout_ms)

    image_url = _wait_for_new_image_url(page, existing_urls, timeout_seconds)
    if not image_url:
        raise RuntimeError("Timed out waiting for the generated image URL.")
    return _get_full_res_image_url(page, image_url, timeout_ms)


def _wait_for_new_image_url(
    page, existing_urls: Set[str], timeout_seconds: int
) -> Optional[str]:
    start = time.time()
    last_log = start
    while time.time() - start < timeout_seconds:
        urls = _get_image_urls(page)
        for url in reversed(urls):
            if url not in existing_urls:
                return url
        now = time.time()
        if now - last_log >= 15:
            elapsed = int(now - start)
            print(f"[midjourney] waiting for image... {elapsed}s")
            last_log = now
        time.sleep(2)
    return None


def _normalize_prompts(prompts: List[str]) -> List[str]:
    cleaned: List[str] = []
    for raw in prompts:
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            normalized = " ".join(stripped.split())
            if normalized.lower().startswith("prompt:"):
                normalized = normalized[7:].lstrip()
            while normalized and normalized[0] in "-*,":
                normalized = normalized[1:].lstrip()
            if normalized and normalized[0].isdigit():
                parts = normalized.split(maxsplit=1)
                if len(parts) == 2 and parts[0].rstrip(".").isdigit():
                    normalized = parts[1].strip()
            if normalized:
                cleaned.append(normalized)
    return cleaned


def _load_prompts_file(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as handle:
        return _normalize_prompts([handle.read()])


def _close_extra_pages(context, keep_page) -> None:
    for extra in list(context.pages):
        if extra == keep_page:
            continue
        try:
            extra.close()
        except Exception:
            pass


def _get_or_create_page(context, timeout_seconds: int):
    pages = list(context.pages)
    page = None
    for candidate in pages:
        url = (candidate.url or "").strip().lower()
        if url and url != "about:blank":
            page = candidate
            break
    if page is None:
        page = pages[0] if pages else context.new_page()
    _close_extra_pages(context, page)
    page.set_default_timeout(timeout_seconds * 1000)
    return page


def _install_page_guard(context, keep_page) -> None:
    def _handle_page(page) -> None:
        if page == keep_page:
            return
        try:
            url = (page.url or "").strip().lower()
            if not url or url == "about:blank":
                page.close()
                return
            page.close()
        except Exception:
            pass

    try:
        context.on("page", _handle_page)
    except Exception:
        pass


def run(
    prompts: List[str],
    headless: bool,
    timeout_seconds: int,
    profile_dir: str,
    cookies_file: str,
    storage_state_path: Optional[str],
    allow_manual_login: bool,
) -> List[str]:
    email = _require_env("DISCORD_EMAIL")
    password = _require_env("DISCORD_PASSWORD")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile_dir,
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        cookies = _load_midjourney_cookies(cookies_file)
        if cookies:
            try:
                context.add_cookies(cookies)
                print(f"[midjourney] loaded {len(cookies)} cookies from {cookies_file}")
            except Exception:
                print("[midjourney] failed to load cookies; continuing without them")
        page = _get_or_create_page(context, timeout_seconds)

        logged_in = _ensure_midjourney_logged_in(
            page,
            email,
            password,
            timeout_seconds,
            allow_manual=allow_manual_login,
            raise_on_cloudflare=headless,
        )
        if not logged_in:
            raise RuntimeError("Unable to log in to Midjourney.")
        _install_page_guard(context, page)

        if storage_state_path:
            try:
                context.storage_state(path=storage_state_path)
                print(f"[midjourney] saved storage state to {storage_state_path}")
            except Exception:
                print("[midjourney] failed to save storage state")

        image_urls: List[str] = []
        for prompt in prompts:
            image_urls.append(_process_prompt(page, prompt, timeout_seconds))

        context.close()
        return image_urls


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automate Discord Midjourney prompts and return image URLs."
    )
    parser.add_argument(
        "--prompt",
        action="append",
        help="Prompt to send to Midjourney. Can be provided multiple times.",
    )
    parser.add_argument(
        "--prompts-file",
        help="Path to a text file with one prompt per line (numbered lines supported).",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode.",
    )
    parser.add_argument(
        "--watch-queue",
        action="store_true",
        help="Watch a queue file and process prompts continuously.",
    )
    parser.add_argument(
        "--keep-browser-open",
        action="store_true",
        help="Keep one browser session open while watching the queue.",
    )
    parser.add_argument(
        "--queue-file",
        default=DEFAULT_QUEUE_FILE,
        help="Queue file with one prompt per line.",
    )
    parser.add_argument(
        "--done-file",
        default=DEFAULT_DONE_FILE,
        help="File to append completed prompts.",
    )
    parser.add_argument(
        "--failed-file",
        default=DEFAULT_FAILED_FILE,
        help="File to append failed prompts.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=5,
        help="Polling interval for queue watch mode.",
    )
    parser.add_argument(
        "--exit-when-queue-empty",
        action="store_true",
        help="Exit after the queue has been empty for a while.",
    )
    parser.add_argument(
        "--empty-queue-exit-seconds",
        type=int,
        default=0,
        help="How long the queue must stay empty before exiting (0 disables).",
    )
    parser.add_argument(
        "--max-prompts",
        type=int,
        default=0,
        help="Stop after processing this many prompts (0 disables).",
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=0,
        help="Stop after this many failures (0 disables).",
    )
    parser.add_argument(
        "--one-by-one",
        action="store_true",
        help="Process prompts one at a time, closing the browser between each.",
    )
    parser.add_argument(
        "--bootstrap-headless",
        action="store_true",
        help="Run a headful login first, then relaunch headless for prompts.",
    )
    parser.add_argument(
        "--auto-fallback-headful",
        action="store_true",
        help="If headless is blocked (e.g., Cloudflare), retry the run in headful mode.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Overall timeout for waits.",
    )
    parser.add_argument(
        "--profile-dir",
        default=DEFAULT_PROFILE_DIR,
        help="Persistent profile directory for Discord session.",
    )
    parser.add_argument(
        "--cookies-file",
        default=DEFAULT_COOKIES_PATH,
        help="Path to a Midjourney cookies JSON export (optional).",
    )
    parser.add_argument(
        "--storage-state",
        default=None,
        help="Optional path to save Playwright storage state after login.",
    )
    parser.add_argument(
        "--output-file",
        default="midjourney_urls.txt",
        help="File to append generated image URLs (one per line).",
    )
    return parser.parse_args()


def _bootstrap_headless_session(
    profile_dir: str,
    cookies_file: str,
    timeout_seconds: int,
    storage_state_path: Optional[str],
) -> bool:
    email = _require_env("DISCORD_EMAIL")
    password = _require_env("DISCORD_PASSWORD")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        cookies = _load_midjourney_cookies(cookies_file)
        if cookies:
            try:
                context.add_cookies(cookies)
                print(f"[midjourney] loaded {len(cookies)} cookies from {cookies_file}")
            except Exception:
                print("[midjourney] failed to load cookies; continuing without them")
        page = _get_or_create_page(context, timeout_seconds)

        logged_in = _ensure_midjourney_logged_in(
            page,
            email,
            password,
            timeout_seconds,
            allow_manual=True,
            raise_on_cloudflare=False,
        )

        if storage_state_path:
            try:
                context.storage_state(path=storage_state_path)
                print(f"[midjourney] saved storage state to {storage_state_path}")
            except Exception:
                print("[midjourney] failed to save storage state")

        context.close()
        return logged_in


def main() -> int:
    args = parse_args()
    try:
        _load_dotenv(os.path.join(os.getcwd(), ".env"))
        prompts: List[str] = []
        if args.prompt:
            prompts.extend(_normalize_prompts(args.prompt))
        if args.prompts_file:
            prompts.extend(_load_prompts_file(args.prompts_file))
        if not prompts and not args.watch_queue:
            raise ValueError("At least one prompt is required.")

        headless_run = args.headless
        if args.bootstrap_headless:
            if not _bootstrap_headless_session(
                profile_dir=args.profile_dir,
                cookies_file=args.cookies_file,
                timeout_seconds=args.timeout_seconds,
                storage_state_path=args.storage_state,
            ):
                raise RuntimeError(
                    "Headful bootstrap did not complete login. Finish verification in the browser and retry."
                )
            headless_run = True

        def _run_with_fallback(
            run_prompts: List[str], prefer_headless: bool
        ) -> tuple[List[str], bool]:
            try:
                return (
                    run(
                        prompts=run_prompts,
                        headless=prefer_headless,
                        timeout_seconds=args.timeout_seconds,
                        profile_dir=args.profile_dir,
                        cookies_file=args.cookies_file,
                        storage_state_path=args.storage_state,
                        allow_manual_login=not prefer_headless,
                    ),
                    False,
                )
            except CloudflareChallengeError as exc:
                if prefer_headless and args.auto_fallback_headful:
                    print("[midjourney] headless blocked; retrying headful")
                    return (
                        run(
                            prompts=run_prompts,
                            headless=False,
                            timeout_seconds=args.timeout_seconds,
                            profile_dir=args.profile_dir,
                            cookies_file=args.cookies_file,
                            storage_state_path=args.storage_state,
                            allow_manual_login=True,
                        ),
                        True,
                    )
                raise exc

        if args.watch_queue and args.keep_browser_open:
            if prompts:
                for prompt in prompts:
                    _append_line(args.queue_file, prompt)
                prompts = []

            email = _require_env("DISCORD_EMAIL")
            password = _require_env("DISCORD_PASSWORD")

            with sync_playwright() as p:
                current_headless = headless_run
                context = None
                page = None
                processed_count = 0
                failure_count = 0
                last_activity = time.time()

                while True:
                    if args.max_prompts and processed_count >= args.max_prompts:
                        print("[midjourney] max prompts reached; exiting")
                        break
                    if args.max_failures and failure_count >= args.max_failures:
                        print("[midjourney] max failures reached; exiting")
                        break

                    if context is None:
                        context = p.chromium.launch_persistent_context(
                            args.profile_dir,
                            headless=current_headless,
                            args=["--disable-blink-features=AutomationControlled"],
                        )
                        cookies = _load_midjourney_cookies(args.cookies_file)
                        if cookies:
                            try:
                                context.add_cookies(cookies)
                                print(
                                    f"[midjourney] loaded {len(cookies)} cookies from {args.cookies_file}"
                                )
                            except Exception:
                                print("[midjourney] failed to load cookies; continuing without them")
                        page = _get_or_create_page(context, args.timeout_seconds)

                        try:
                            logged_in = _ensure_midjourney_logged_in(
                                page,
                                email,
                                password,
                                args.timeout_seconds,
                                allow_manual=not current_headless,
                                raise_on_cloudflare=current_headless,
                            )
                            if not logged_in:
                                raise RuntimeError("Unable to log in to Midjourney.")
                            _install_page_guard(context, page)
                        except CloudflareChallengeError:
                            if current_headless and args.auto_fallback_headful:
                                print("[midjourney] headless blocked; retrying headful")
                                try:
                                    context.close()
                                except Exception:
                                    pass
                                context = None
                                page = None
                                current_headless = False
                                continue
                            raise

                        if args.storage_state:
                            try:
                                context.storage_state(path=args.storage_state)
                                print(f"[midjourney] saved storage state to {args.storage_state}")
                            except Exception:
                                print("[midjourney] failed to save storage state")

                    queue_prompts = _read_queue_file(args.queue_file)
                    if not queue_prompts:
                        if args.exit_when_queue_empty and args.empty_queue_exit_seconds > 0:
                            if time.time() - last_activity >= args.empty_queue_exit_seconds:
                                print("[midjourney] queue empty; exiting")
                                break
                        time.sleep(max(1, args.poll_seconds))
                        continue

                    current_prompt = queue_prompts.pop(0)
                    _write_queue_file(args.queue_file, queue_prompts)
                    try:
                        image_url = _process_prompt(page, current_prompt, args.timeout_seconds)
                        print(image_url)
                        _append_line(args.output_file, image_url)
                        _append_line(args.done_file, f"{current_prompt}\t{image_url}")
                        processed_count += 1
                        last_activity = time.time()
                    except Exception as exc:
                        _append_line(args.failed_file, f"{current_prompt}\t{exc}")
                        failure_count += 1
                        last_activity = time.time()
        elif args.watch_queue:
            if prompts:
                for prompt in prompts:
                    _append_line(args.queue_file, prompt)
                prompts = []

            sticky_headful = False
            processed_count = 0
            failure_count = 0
            last_activity = time.time()
            while True:
                if args.max_prompts and processed_count >= args.max_prompts:
                    print("[midjourney] max prompts reached; exiting")
                    break
                if args.max_failures and failure_count >= args.max_failures:
                    print("[midjourney] max failures reached; exiting")
                    break

                queue_prompts = _read_queue_file(args.queue_file)
                if not queue_prompts:
                    if args.exit_when_queue_empty and args.empty_queue_exit_seconds > 0:
                        if time.time() - last_activity >= args.empty_queue_exit_seconds:
                            print("[midjourney] queue empty; exiting")
                            break
                    time.sleep(max(1, args.poll_seconds))
                    continue

                current = queue_prompts.pop(0)
                _write_queue_file(args.queue_file, queue_prompts)

                prefer_headless = headless_run and not sticky_headful
                try:
                    image_urls, fell_back = _run_with_fallback([current], prefer_headless)
                    if fell_back:
                        sticky_headful = True
                    for image_url in image_urls:
                        print(image_url)
                        try:
                            _append_line(args.output_file, image_url)
                            _append_line(args.done_file, f"{current}\t{image_url}")
                        except Exception:
                            print("[midjourney] failed to write output file")
                    processed_count += 1
                    last_activity = time.time()
                except Exception as exc:
                    _append_line(args.failed_file, f"{current}\t{exc}")
                    failure_count += 1
                    last_activity = time.time()
        elif args.one_by_one:
            sticky_headful = False
            for prompt in prompts:
                prefer_headless = headless_run and not sticky_headful
                image_urls, fell_back = _run_with_fallback([prompt], prefer_headless)
                if fell_back:
                    sticky_headful = True
                for image_url in image_urls:
                    print(image_url)
                    try:
                        with open(args.output_file, "a", encoding="utf-8") as handle:
                            handle.write(f"{image_url}\n")
                    except Exception:
                        print("[midjourney] failed to write output file")
        else:
            image_urls, _ = _run_with_fallback(prompts, headless_run)
            for image_url in image_urls:
                print(image_url)
                try:
                    with open(args.output_file, "a", encoding="utf-8") as handle:
                        handle.write(f"{image_url}\n")
                except Exception:
                    print("[midjourney] failed to write output file")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
