#!/usr/bin/env python3
import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

BLOCKED_DOMAINS = (
    "pinterest.com",
    "www.pinterest.com",
    "pin.it",
    "i.pinimg.com",
    "pinimg.com",
)

IGNORED_DOMAINS = (
    "schema.org",
    "w3.org",
    "arkoselabs.com",
    "amazon-adsystem.com",
    "daily.co",
    "pluot.blue",
    "google.com",
    "googleusercontent.com",
    "chrome.google.com",
)

STOPWORDS = {
    "a",
    "an",
    "and",
    "or",
    "the",
    "of",
    "with",
    "for",
    "to",
    "in",
    "on",
    "at",
    "from",
    "by",
    "recipe",
    "easy",
    "best",
    "simple",
    "quick",
    "homemade",
    "how",
    "make",
    "pin",
    "pinterest",
    "przepis",
    "przepisy",
    "latwy",
    "łatwy",
    "latwe",
    "łatwe",
    "szybki",
    "szybkie",
    "domowy",
    "domowe",
}

_WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)

MAX_HEADINGS = 6
MAX_PARAGRAPHS = 6
MAX_IMAGE_ALTS = 8


def load_dotenv(path=".env"):
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if raw.startswith("export "):
                raw = raw[len("export ") :].strip()
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or key in os.environ:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value


class PinHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.title = ""
        self.base_href = ""
        self.anchor_candidates = []
        self.noscript_blocks = []
        self.headings = []
        self.paragraphs = []
        self.image_alts = []
        self._in_title = False
        self._in_anchor = False
        self._anchor_text = []
        self._current_anchor = None
        self._in_noscript = False
        self._noscript_buffer = []
        self._text_tag = None
        self._text_buffer = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "meta":
            prop = attrs_dict.get("property") or attrs_dict.get("name")
            content = attrs_dict.get("content")
            if prop and content:
                self.meta[prop.lower()] = content
        elif tag == "base":
            href = attrs_dict.get("href")
            if href:
                self.base_href = href
        elif tag == "title":
            self._in_title = True
        elif tag == "img":
            alt = attrs_dict.get("alt")
            if alt and len(self.image_alts) < MAX_IMAGE_ALTS:
                self.image_alts.append(alt.strip())
        elif tag in {"h1", "h2", "p"}:
            self._text_tag = tag
            self._text_buffer = []
        elif tag == "a":
            href = attrs_dict.get("href")
            if not href:
                return
            anchor = {
                "href": href,
                "data_test_id": attrs_dict.get("data-test-id") or "",
                "aria_label": attrs_dict.get("aria-label") or "",
                "title": attrs_dict.get("title") or "",
                "rel": attrs_dict.get("rel") or "",
                "text": "",
            }
            self.anchor_candidates.append(anchor)
            self._current_anchor = anchor
            self._in_anchor = True
            self._anchor_text = []
        elif tag == "noscript":
            self._in_noscript = True
            self._noscript_buffer = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in {"h1", "h2", "p"} and self._text_tag == tag:
            text_value = "".join(self._text_buffer).strip()
            if text_value:
                if tag in {"h1", "h2"} and len(self.headings) < MAX_HEADINGS:
                    self.headings.append(text_value)
                elif tag == "p" and len(self.paragraphs) < MAX_PARAGRAPHS:
                    self.paragraphs.append(text_value)
            self._text_tag = None
            self._text_buffer = []
        elif tag == "a":
            if self._current_anchor is not None:
                self._current_anchor["text"] = "".join(self._anchor_text).strip()
            self._current_anchor = None
            self._in_anchor = False
            self._anchor_text = []
        elif tag == "noscript":
            if self._in_noscript:
                block = "".join(self._noscript_buffer).strip()
                if block:
                    self.noscript_blocks.append(block)
            self._in_noscript = False
            self._noscript_buffer = []

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_anchor:
            self._anchor_text.append(data)
        if self._in_noscript:
            self._noscript_buffer.append(data)
        if self._text_tag:
            self._text_buffer.append(data)


def normalize_url(raw):
    if not raw:
        return None
    value = raw.strip().strip('"').strip("'")
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("www."):
        return "https://" + value
    if value.startswith("pinterest.com/") or value.startswith("www.pinterest.com/"):
        return "https://" + value
    return value


def normalize_request_url(url):
    if not url:
        return ""
    cleaned = url.strip()
    if not cleaned:
        return ""
    parsed = urllib.parse.urlsplit(cleaned)
    if not parsed.scheme or not parsed.netloc:
        return cleaned
    hostname = parsed.hostname or ""
    if not hostname:
        return ""
    if ":" in hostname:
        host_idna = hostname
    else:
        try:
            host_idna = hostname.encode("idna").decode("ascii")
        except UnicodeError:
            return ""
        if not is_valid_hostname(host_idna):
            return ""
    if ":" in host_idna and not host_idna.startswith("["):
        host_idna = f"[{host_idna}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    userinfo = ""
    if parsed.username:
        userinfo = urllib.parse.quote(parsed.username, safe="")
        if parsed.password is not None:
            userinfo += ":" + urllib.parse.quote(parsed.password, safe="")
        userinfo += "@"
    netloc = f"{userinfo}{host_idna}"
    if port:
        netloc = f"{netloc}:{port}"
    path = urllib.parse.quote(parsed.path, safe="/%:@&=+$,;~*'()")
    query = urllib.parse.quote(parsed.query, safe="=&%:@/+")
    fragment = urllib.parse.quote(parsed.fragment, safe="=&%:@/+")
    return urllib.parse.urlunsplit((parsed.scheme, netloc, path, query, fragment))


def is_valid_hostname(hostname):
    if not hostname:
        return False
    trimmed = hostname[:-1] if hostname.endswith(".") else hostname
    if not trimmed:
        return False
    if len(trimmed) > 253:
        return False
    for label in trimmed.split("."):
        if not label or len(label) > 63:
            return False
        for ch in label:
            codepoint = ord(ch)
            if codepoint <= 32 or codepoint == 127:
                return False
    return True


def extract_urls_from_text(text):
    return re.findall(r"https?://[^\s\"'<>]+", text)


def extract_pin_id(url):
    match = re.search(r"/pin/(\d+)", url)
    return match.group(1) if match else None


def is_external_url(url):
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc:
        return False
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    for blocked in BLOCKED_DOMAINS:
        if host == blocked or host.endswith("." + blocked):
            return False
    return True


def is_ignored_domain(url):
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    for ignored in IGNORED_DOMAINS:
        if host == ignored or host.endswith("." + ignored):
            return True
    return False


def is_candidate_external_url(url):
    return bool(url) and is_external_url(url) and not is_ignored_domain(url)


def title_looks_like_domain(title, visit_url):
    if not title:
        return True
    cleaned = title.strip()
    if not cleaned:
        return True
    host = urllib.parse.urlparse(visit_url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    if cleaned.lower() == host:
        return True
    if re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cleaned):
        return True
    if host.replace(".", "") in re.sub(r"[\s\-\|:_]+", "", cleaned.lower()):
        if len(cleaned.split()) <= 2:
            return True
    return False


def title_looks_like_person(title):
    if not title:
        return False
    cleaned = title.strip()
    if not cleaned:
        return False
    if re.search(r"[@#/:_]", cleaned):
        return False
    return bool(re.fullmatch(r"[A-Z][a-z]+(?: [A-Z][a-z]+){1,2}", cleaned))


def title_from_url_slug(visit_url):
    if not visit_url:
        return ""
    parsed = urllib.parse.urlparse(visit_url)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return ""
    slug = parts[-1]
    slug = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", slug)
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", slug)
    slug = slug.replace("-", " ").replace("_", " ").strip()
    if not slug:
        return ""
    return " ".join(word.capitalize() if word.isalpha() else word for word in slug.split())


def normalize_recipe_title(title):
    if not title:
        return ""
    cleaned = title.strip()
    cleaned = cleaned.replace("“", '"').replace("”", '"').replace("’", "'")
    cleaned = cleaned.strip('"').strip("'")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.replace('"', "")

    def should_drop_parenthetical(text):
        value = text.strip()
        if not value:
            return True
        if '"' in value or "'" in value:
            return True
        words = _tokenize_words(value)
        if len(words) > 5 or len(value) > 30:
            return True
        marketing = {
            "easy",
            "simple",
            "best",
            "ultimate",
            "homemade",
            "quick",
            "delicious",
            "nutritious",
            "healthy",
            "natural",
            "special",
            "favorite",
            "reward",
            "snack",
            "treat",
            "treats",
            "recipe",
            "przepis",
            "przepisy",
            "łatwy",
            "łatwe",
            "szybki",
            "szybkie",
            "domowy",
            "domowe",
        }
        return any(word in marketing for word in words)

    if "(" in cleaned and ")" in cleaned:
        rebuilt = []
        last_idx = 0
        for match in re.finditer(r"\(([^)]*)\)", cleaned):
            rebuilt.append(cleaned[last_idx:match.start()])
            if not should_drop_parenthetical(match.group(1)):
                rebuilt.append(f"({match.group(1).strip()})")
            last_idx = match.end()
        rebuilt.append(cleaned[last_idx:])
        cleaned = "".join(rebuilt)
        cleaned = re.sub(r"\s+\)", ")", cleaned)
        cleaned = re.sub(r"\(\s+", "(", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

    split_markers = [" | ", " – ", " — ", " - "]
    for marker in split_markers:
        if marker in cleaned:
            left, right = cleaned.split(marker, 1)
            right_lower = right.lower()
            if any(token in right_lower for token in ("pinterest", "recipe", "recipes", "blog", "kitchen")):
                cleaned = left.strip()
                break
            if re.search(r"\.(com|net|org|io|co)(\b|$)", right_lower):
                cleaned = left.strip()
                break
    if ":" in cleaned:
        left, right = cleaned.split(":", 1)
        right_lower = right.lower()
        if any(
            token in right_lower
            for token in (
                "easy",
                "simple",
                "best",
                "ultimate",
                "homemade",
                "quick",
                "delicious",
                "nutritious",
                "healthy",
                "natural",
                "special",
                "favorite",
                "reward",
                "snack",
                "treat",
                "treats",
                "recipe",
                "przepis",
                "przepisy",
                "łatwy",
                "łatwe",
                "szybki",
                "szybkie",
                "domowy",
                "domowe",
            )
        ):
            cleaned = left.strip()
        elif len(cleaned) > 90 and len(left.strip()) >= 12:
            cleaned = left.strip()

    cleaned = re.sub(r"\b(?:recipe|przepis|przepisy)\b$", "", cleaned, flags=re.I).strip()
    return cleaned.strip()


def unwrap_pinterest_redirect(url):
    if not url:
        return url
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if "pinterest.com" not in host:
        return url
    if path in {"/out", "/redirect", "/redirect/"}:
        query = urllib.parse.parse_qs(parsed.query)
        for key in ("url", "u", "dest"):
            if key in query and query[key]:
                return query[key][0]
    return url


def make_absolute_url(url, base_url):
    if not url:
        return ""
    if base_url:
        return urllib.parse.urljoin(base_url, url)
    return url


def decode_escaped_text(value):
    if value is None:
        return ""
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value.replace("\\/", "/")


def extract_visit_from_meta(meta, base_url):
    if not meta:
        return ""
    keys = (
        "pinterestapp:source",
        "pinterestapp:source_url",
        "pinterestapp:sourceurl",
        "pin:source",
        "og:see_also",
        "source_url",
        "sourceurl",
        "original_url",
        "canonical_url",
    )
    for key in keys:
        candidate = meta.get(key)
        if not candidate:
            continue
        url = unwrap_pinterest_redirect(make_absolute_url(candidate, base_url))
        if is_external_url(url):
            return url
    return ""


def score_anchor(anchor):
    if not anchor:
        return 0
    score = 0
    dtid = (anchor.get("data_test_id") or "").lower()
    text = (anchor.get("text") or "").lower()
    aria_label = (anchor.get("aria_label") or "").lower()
    title = (anchor.get("title") or "").lower()
    rel = (anchor.get("rel") or "").lower()
    href = (anchor.get("href") or "").lower()
    if dtid in {"pinlink", "pin-link", "pinlinktext", "pin-link-text"}:
        score += 6
    if dtid in {"closeup-action-link", "closeup-actions-link", "outbound-link", "external-link"}:
        score += 6
    if "visit" in dtid or "visit" in text or "visit" in aria_label or "visit" in title:
        score += 4
    if "source" in text or "source" in aria_label:
        score += 2
    if "recipe" in text or "recipe" in aria_label:
        score += 1
    if "/out/" in href or "redirect" in href:
        score += 3
    if "nofollow" in rel:
        score += 1
    return score


def extract_visit_from_anchors(anchors, base_url):
    if not anchors:
        return ""
    best_url = ""
    best_score = -1
    for anchor in anchors:
        href = anchor.get("href")
        if not href:
            continue
        url = unwrap_pinterest_redirect(make_absolute_url(href, base_url))
        if not is_external_url(url):
            continue
        score = score_anchor(anchor)
        if score > best_score:
            best_score = score
            best_url = url
    return best_url


def extract_visit_from_text(html_text, base_url):
    if not html_text:
        return ""
    text = html.unescape(html_text)
    candidates = []
    key_scores = {
        "link": 6,
        "source_url": 6,
        "sourceUrl": 6,
        "origin_url": 6,
        "originUrl": 6,
        "canonical_url": 5,
        "canonicalUrl": 5,
        "url": 2,
    }
    for key, weight in key_scores.items():
        pattern = rf'"{re.escape(key)}"\s*:\s*"([^"]+)"'
        for match in re.finditer(pattern, text):
            value = decode_escaped_text(match.group(1))
            candidates.append((value, weight))
    for match in re.finditer(r"/out/\?url=([^\"'&]+)", text):
        value = urllib.parse.unquote(match.group(1))
        candidates.append((value, 5))

    best_url = ""
    best_score = -1
    for value, weight in candidates:
        url = unwrap_pinterest_redirect(make_absolute_url(value, base_url))
        if not is_external_url(url):
            continue
        if weight > best_score:
            best_score = weight
            best_url = url
    return best_url


def score_url_key(key_path):
    if not key_path:
        return 0
    key = key_path.lower()
    score = 0
    if "external" in key:
        score += 6
    if "outgoing" in key or "destination" in key:
        score += 6
    if "canonical" in key or "origin" in key or "source" in key:
        score += 5
    if "link" in key:
        score += 4
    if "url" in key:
        score += 3
    if "image" in key or "thumbnail" in key or "thumb" in key or "avatar" in key:
        score -= 6
    return score


def extract_external_url_from_dict(data):
    if data is None:
        return ""
    candidates = []
    stack = [([], data)]
    while stack:
        path, value = stack.pop()
        if isinstance(value, dict):
            for key, item in value.items():
                stack.append((path + [str(key)], item))
            continue
        if isinstance(value, list):
            for item in value:
                stack.append((path, item))
            continue
        if not isinstance(value, str):
            continue
        key_path = ".".join(path)
        for raw in extract_urls_from_text(value) or [value]:
            normalized = normalize_url(raw)
            if not normalized:
                continue
            url = unwrap_pinterest_redirect(normalized)
            if not is_candidate_external_url(url):
                continue
            candidates.append((score_url_key(key_path), url))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    return candidates[0][1]


def extract_external_url_from_html(html_text):
    if not html_text:
        return ""
    candidates = []
    for raw in extract_urls_from_text(html_text):
        normalized = normalize_url(raw)
        if not normalized:
            continue
        try:
            url = unwrap_pinterest_redirect(normalized)
        except ValueError:
            continue
        if not is_candidate_external_url(url):
            continue
        parsed = urllib.parse.urlparse(url)
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        score = 0
        if parsed.scheme == "https":
            score += 1
        if parsed.path and parsed.path != "/":
            score += 2
        if "recipe" in parsed.path:
            score += 2
        if re.search(r"/\d{4}/\d{2}/", parsed.path):
            score += 2
        if "blog" in host or "blog" in parsed.path:
            score += 1
        candidates.append((score, url))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    return candidates[0][1]


def call_openai_chat(api_key, model, messages, timeout, temperature, max_tokens):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
    }
    retries = 1
    for attempt in range(retries + 1):
        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                return json.loads(text)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            if (
                exc.code == 400
                and "max_completion_tokens" in payload
                and "max_completion_tokens" in detail
                and "max_tokens" in detail
            ):
                payload["max_tokens"] = payload.pop("max_completion_tokens")
                if attempt < retries:
                    print(
                        "OpenAI model rejected max_completion_tokens; retrying with max_tokens...",
                        file=sys.stderr,
                    )
                    continue
            print(f"OpenAI request failed: HTTP {exc.code} {detail}", file=sys.stderr)
            return None
        except urllib.error.URLError as exc:
            if attempt < retries:
                print(
                    f"OpenAI request failed (attempt {attempt + 1}/{retries + 1}): {exc}; retrying...",
                    file=sys.stderr,
                )
                continue
            print(f"OpenAI request failed: {exc}", file=sys.stderr)
        except TimeoutError as exc:
            if attempt < retries:
                print(
                    f"OpenAI request timed out (attempt {attempt + 1}/{retries + 1}); retrying...",
                    file=sys.stderr,
                )
                continue
            print(f"OpenAI request timed out: {exc}", file=sys.stderr)
        except json.JSONDecodeError:
            print("OpenAI response was not valid JSON.", file=sys.stderr)
            return None
    return None


def parse_openai_json(content):
    if not content:
        return None
    text = content.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def normalize_openai_keywords(value):
    if not value:
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[,;\n]+", value)
    elif isinstance(value, list):
        raw_items = value
    else:
        return []
    keywords = []
    seen = set()
    for item in raw_items:
        token = str(item).strip().strip('"').strip("'")
        if not token:
            continue
        token = re.sub(r"\s+", " ", token.lower()).strip()
        if " " not in token and len(token) <= 2:
            continue
        if " " not in token and token in STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)
    return keywords


def _tokenize_words(text):
    if not text:
        return []
    return [match.group(0).lower() for match in _WORD_RE.finditer(text)]


def build_openai_prompt(context):
    pin_title = context.get("pin_title", "")
    pin_description = context.get("pin_description", "")
    image_alt_text = context.get("image_alt_text", "")
    site_title = context.get("site_title", "")
    site_description = context.get("site_description", "")
    site_recipe_name = context.get("site_recipe_name", "")
    snippets = context.get("snippets", [])[:10]

    lines = [
        "You are a smart assistant specialized in food recipes and recipe name detection.",
        "Pins can be in any language.",
        "",
        "Your job: Extract the EXACT recipe name and a concise keyword list from a Pinterest pin.",
        "",
        "IMPORTANT CONTEXT:",
    ]
    if pin_title:
        lines.append(f'- PIN TITLE: "{pin_title}"')
    if pin_description:
        lines.append(f'- PIN DESCRIPTION: "{pin_description}"')
    if image_alt_text:
        lines.append(f'- IMAGE ALT TEXT: "{image_alt_text}"')
    if site_title:
        lines.append(f'- VISIT SITE TITLE: "{site_title}"')
    if site_description:
        lines.append(f'- VISIT SITE DESCRIPTION: "{site_description}"')
    if site_recipe_name:
        lines.append(f'- VISIT SITE RECIPE NAME: "{site_recipe_name}"')

    if snippets:
        lines.append("")
        lines.append("Additional text snippets from the pin:")
        for snippet in snippets:
            lines.append(f"- {snippet}")

    lines.extend(
        [
            "",
            "INSTRUCTIONS:",
            "1. Focus on the pin title, description, and image alt text first.",
            "2. Identify the specific dish name (not categories like Dessert or Dinner).",
            "3. Ignore generic phrases like \"Pin on Desserts\" or \"Food Ideas\".",
            "4. Remove unnecessary words like Recipe, Easy, Homemade, Best from the recipe name.",
            "5. Output ONLY valid JSON, no commentary or extra text.",
            "6. Keep the recipe name in the original language found in the pin/site context. Do not translate.",
            "7. Keywords should be 5-12 short terms, lower-case, no duplicates, no generic words.",
            "8. Keep keywords in the original language when possible (no forced translation).",
            "",
            "Return JSON only, in this exact shape:",
            '{"recipe_name":"...","keywords":["...","..."]}',
        ]
    )
    return "\n".join(lines)


def extract_with_openai(context, api_key, model, timeout, temperature, max_tokens):
    if not context or not api_key:
        return None
    prompt = build_openai_prompt(context)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a recipe name detection specialist. "
                "Extract the exact recipe name and keywords from Pinterest pins. "
                "Pins may be multilingual; keep outputs in the original language."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    response = call_openai_chat(
        api_key, model, messages, timeout, temperature, max_tokens
    )
    if not response:
        return None
    content = (
        response.get("choices", [{}])[0].get("message", {}).get("content", "")
    )
    data = parse_openai_json(content)
    if not isinstance(data, dict):
        return None
    recipe_name = data.get("recipe_name") or data.get("recipe") or data.get("name")
    keywords = data.get("keywords") or data.get("keyword_list") or data.get("tags")
    recipe_name = clean_title(recipe_name) if recipe_name else ""
    normalized_keywords = normalize_openai_keywords(keywords)
    return {"recipe_name": recipe_name, "keywords": normalized_keywords}


def fetch_url(url, timeout, accept_language=""):
    request_url = normalize_request_url(url)
    if not request_url:
        raise urllib.error.URLError(f"Invalid URL: {url}")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    }
    accept_language = (accept_language or "").strip()
    if accept_language:
        headers["Accept-Language"] = accept_language
    req = urllib.request.Request(request_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            body = resp.read()
            text = body.decode(charset, errors="replace")
            return resp.getcode(), text
    except TimeoutError as exc:
        raise urllib.error.URLError(f"Timed out fetching {url}") from exc
    except (UnicodeEncodeError, UnicodeError) as exc:
        raise urllib.error.URLError(f"Invalid URL: {url}") from exc


def fetch_pin_api(pin_id, timeout, accept_language=""):
    if not pin_id:
        return None
    api_url = f"https://api.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}"
    try:
        status, text = fetch_url(api_url, timeout, accept_language)
    except urllib.error.URLError:
        return None
    if status != 200:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    pins = extract_pins_from_payload(data)
    if not pins:
        return None
    if isinstance(pins, dict):
        return pins
    return pins[0]


def fetch_pin_resource(pin_id, timeout, accept_language=""):
    if not pin_id:
        return None
    data = {
        "options": {"id": str(pin_id), "field_set_key": "detailed"},
        "context": {},
    }
    query = urllib.parse.urlencode(
        {
            "source_url": f"/pin/{pin_id}/",
            "data": json.dumps(data, separators=(",", ":")),
        }
    )
    resource_url = f"https://www.pinterest.com/resource/PinResource/get/?{query}"
    try:
        status, text = fetch_url(resource_url, timeout, accept_language)
    except urllib.error.URLError:
        return None
    if status != 200:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    resource = payload.get("resource_response", {}).get("data")
    if isinstance(resource, dict):
        return resource
    if isinstance(resource, list) and resource:
        return resource[0]
    return None


def extract_pins_from_payload(data):
    if isinstance(data, dict):
        direct_pins = data.get("data")
        if isinstance(direct_pins, dict) and isinstance(direct_pins.get("pins"), list):
            return direct_pins["pins"]
        if isinstance(data.get("pins"), list):
            return data["pins"]
        if any(key in data for key in ("id", "pin_id")):
            return [data]
    if isinstance(data, list):
        if data and all(isinstance(item, dict) for item in data):
            if any("id" in item or "pin_id" in item for item in data):
                return data
    for obj in iter_dicts(data):
        if isinstance(obj, dict) and isinstance(obj.get("pins"), list):
            return obj["pins"]
    return []


def iter_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from iter_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from iter_dicts(value)


def score_pin_dict(data, pin_id):
    score = 0
    if not isinstance(data, dict):
        return score
    if pin_id:
        if str(data.get("id")) == str(pin_id) or str(data.get("pin_id")) == str(pin_id):
            score += 6
    if "link" in data:
        score += 2
        if is_external_url(data.get("link")):
            score += 4
    if any(key in data for key in ("title", "grid_title", "description", "name")):
        score += 2
    if isinstance(data.get("rich_metadata"), dict):
        score += 1
    return score


def pick_best_pin_data(objects, pin_id):
    best = None
    best_score = -1
    for data in objects:
        score = score_pin_dict(data, pin_id)
        if score > best_score:
            best_score = score
            best = data
    return best


def extract_fields_from_dict(data):
    if not isinstance(data, dict):
        return "", ""
    title = (
        data.get("title")
        or data.get("grid_title")
        or data.get("name")
        or data.get("description")
    )
    visit_url = (
        data.get("link")
        or data.get("url")
        or data.get("external_url")
        or data.get("source_url")
        or data.get("origin_url")
        or data.get("canonical_url")
        or ""
    )
    if visit_url and not is_candidate_external_url(visit_url):
        visit_url = ""
    rich = data.get("rich_metadata")
    if isinstance(rich, dict):
        if not title:
            title = rich.get("title") or rich.get("name")
        if not visit_url:
            visit_url = (
                rich.get("url")
                or rich.get("link")
                or rich.get("external_url")
                or rich.get("canonical_url")
            )
        if not visit_url:
            nested = rich.get("article") or rich.get("recipe") or rich.get("story_pin_data")
            if isinstance(nested, dict):
                visit_url = nested.get("url") or nested.get("link") or nested.get("external_url")
        if visit_url and not is_candidate_external_url(visit_url):
            visit_url = ""
    if not visit_url:
        visit_url = extract_external_url_from_dict(data)
    return title or "", visit_url or ""


def extract_json_blobs(html_text):
    blobs = []
    patterns = [
        r'<script[^>]+id="__PWS_DATA__"[^>]*>(.*?)</script>',
        r"window\.__PWS_DATA__\s*=\s*({.*?})\s*;",
        r"__PWS_INITIAL_PROPS__\s*=\s*({.*?})\s*;",
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        r'<script[^>]+type="application/json"[^>]*>(.*?)</script>',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, html_text, re.S | re.I):
            blobs.append(match.group(1))
    return blobs


def _extract_meta_content(html_text, patterns):
    for pattern in patterns:
        match = re.search(pattern, html_text, re.I | re.S)
        if match:
            value = html.unescape(match.group(1)).strip()
            if value:
                return value
    return ""


def _find_recipe_name_from_json(data):
    if isinstance(data, dict):
        data_type = data.get("@type") or data.get("type")
        if isinstance(data_type, list):
            types = [str(value).lower() for value in data_type]
        else:
            types = [str(data_type).lower()] if data_type else []
        if "recipe" in types and data.get("name"):
            return str(data.get("name")).strip()
        if "@graph" in data:
            result = _find_recipe_name_from_json(data.get("@graph"))
            if result:
                return result
        for value in data.values():
            result = _find_recipe_name_from_json(value)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_recipe_name_from_json(item)
            if result:
                return result
    return ""


def extract_title_from_recipe_page(url, timeout, accept_language=""):
    try:
        status, html_text = fetch_url(url, timeout, accept_language)
    except urllib.error.URLError:
        return "", "", ""
    if not html_text:
        return "", "", ""
    recipe_name = ""
    for blob in extract_json_blobs(html_text):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        recipe_name = _find_recipe_name_from_json(data)
        if recipe_name:
            break
    title = _extract_meta_content(
        html_text,
        [
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)["\']',
            r"<title[^>]*>(.*?)</title>",
        ],
    )
    description = _extract_meta_content(
        html_text,
        [
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        ],
    )
    return recipe_name.strip(), title.strip(), description.strip()


def extract_from_html(html_text, pin_id, base_url):
    parser = PinHTMLParser()
    parser.feed(html_text)

    base_href = parser.base_href or base_url
    meta_title = parser.meta.get("og:title") or parser.meta.get("twitter:title")
    meta_description = parser.meta.get("og:description") or parser.meta.get("description")
    title_tag = parser.title.strip() if parser.title else ""

    title = ""
    visit_url = ""

    for blob in extract_json_blobs(html_text):
        for candidate in (blob.strip(), html.unescape(blob.strip())):
            if not candidate:
                continue
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            best = pick_best_pin_data(iter_dicts(data), pin_id)
            candidate_title, candidate_visit = extract_fields_from_dict(best)
            if candidate_title and not title:
                title = candidate_title
            if candidate_visit and not visit_url:
                visit_url = candidate_visit
            if not visit_url:
                visit_url = extract_external_url_from_dict(data)
            if title and visit_url:
                break
        if title and visit_url:
            break

    if not title:
        title = meta_title or title_tag or meta_description or ""

    if not visit_url:
        visit_url = extract_visit_from_meta(parser.meta, base_href)

    if not visit_url:
        visit_url = extract_visit_from_anchors(parser.anchor_candidates, base_href)

    if not visit_url and parser.noscript_blocks:
        for block in parser.noscript_blocks:
            nested = PinHTMLParser()
            nested.feed(block)
            nested_title = (
                nested.meta.get("og:title")
                or nested.meta.get("twitter:title")
                or nested.title.strip()
            )
            if not title and nested_title:
                title = nested_title
            if not visit_url:
                visit_url = extract_visit_from_meta(nested.meta, base_href)
            if not visit_url:
                visit_url = extract_visit_from_anchors(nested.anchor_candidates, base_href)
            if visit_url:
                break

    if not visit_url:
        visit_url = extract_visit_from_text(html_text, base_href)

    if not visit_url:
        visit_url = extract_external_url_from_html(html_text)

    context = build_openai_context(parser)
    return title, visit_url, context


def extract_keywords(title):
    if not title:
        return ""
    tokens = _tokenize_words(title)
    keywords = []
    seen = set()
    for token in tokens:
        if len(token) <= 2 or token in STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)
    return ", ".join(keywords)


def clean_title(title):
    if not title:
        return ""
    cleaned = title.strip()
    cleaned = re.sub(r"\s+\|\s*pinterest\s*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+-\s*pinterest\s*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^pin on\s+", "", cleaned, flags=re.I)
    return cleaned.strip()


def build_openai_context(parser):
    pin_title = (
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
        or parser.title.strip()
    )
    pin_title = clean_title(pin_title)
    pin_description = (
        parser.meta.get("og:description")
        or parser.meta.get("description")
        or parser.meta.get("twitter:description")
        or ""
    )
    image_alt_text = " | ".join([alt for alt in parser.image_alts if alt])
    snippets = []
    for text_value in parser.headings + parser.paragraphs:
        cleaned = text_value.strip()
        if cleaned:
            snippets.append(cleaned)
    return {
        "pin_title": pin_title,
        "pin_description": pin_description.strip(),
        "image_alt_text": image_alt_text.strip(),
        "snippets": snippets,
    }


def collect_urls(args):
    urls = []
    if args.file:
        with open(args.file, "r", encoding="utf-8") as handle:
            for line in handle:
                for match in extract_urls_from_text(line):
                    urls.append(match)

    for raw in args.urls:
        matches = extract_urls_from_text(raw)
        if matches:
            urls.extend(matches)
        else:
            normalized = normalize_url(raw)
            if normalized:
                urls.append(normalized)

    if not urls and not sys.stdin.isatty():
        for line in sys.stdin:
            for match in extract_urls_from_text(line):
                urls.append(match)

    normalized_urls = []
    for value in urls:
        normalized = normalize_url(value)
        if normalized:
            normalized_urls.append(normalized)
    return normalized_urls


def output_rows(rows, fmt, include_header, lists_include_keywords=False):
    if fmt == "json":
        print(json.dumps(rows, indent=2))
        return
    if fmt == "lists":
        output_lists(rows, include_header, lists_include_keywords)
        return
    if fmt == "csv":
        delimiter = ","
    else:
        delimiter = "\t"

    if include_header:
        header = ["recipe", "keywords", "pinterest_url", "visit_site_url"]
        print(delimiter.join(header))

    for row in rows:
        values = [
            row.get("recipe", ""),
            row.get("keywords", ""),
            row.get("pinterest_url", ""),
            row.get("visit_site_url", ""),
        ]
        print(delimiter.join(values))


def output_lists(rows, include_header, lists_include_keywords):
    sections = [("recipe_names", "recipe")]
    if lists_include_keywords:
        sections.append(("keywords", "keywords"))
    sections.extend(
        [
            ("pinterest_urls", "pinterest_url"),
            ("visit_site_urls", "visit_site_url"),
        ]
    )
    for idx, (label, key) in enumerate(sections):
        if include_header:
            print(label)
        for row in rows:
            print(row.get(key, ""))
        if include_header and idx < len(sections) - 1:
            print()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract recipe keyword and Visit Site links from Pinterest pins."
    )
    parser.add_argument("urls", nargs="*", help="Pinterest pin URLs")
    parser.add_argument("-f", "--file", help="File with URLs (one per line)")
    parser.add_argument(
        "--format",
        choices=("tsv", "csv", "json", "lists"),
        default="tsv",
        help="Output format (default: tsv)",
    )
    parser.add_argument("--no-header", action="store_true", help="Skip header row")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout")
    parser.add_argument(
        "--accept-language",
        default="",
        help=(
            "Optional Accept-Language header for Pinterest and recipe page fetches "
            "(e.g. 'pl-PL,pl;q=0.9,en;q=0.8'). If empty, no Accept-Language header is sent."
        ),
    )
    parser.add_argument(
        "--openai",
        action="store_true",
        help="Use OpenAI to extract recipe name and keywords",
    )
    parser.add_argument(
        "--openai-model",
        default="gpt-3.5-turbo",
        help="OpenAI model to use (default: gpt-3.5-turbo)",
    )
    parser.add_argument(
        "--openai-timeout",
        type=float,
        default=30.0,
        help="OpenAI request timeout in seconds",
    )
    parser.add_argument(
        "--openai-temperature",
        type=float,
        default=0.2,
        help="OpenAI temperature (default: 0.2)",
    )
    parser.add_argument(
        "--openai-max-tokens",
        type=int,
        default=120,
        help="OpenAI max tokens (default: 120)",
    )
    parser.add_argument(
        "--lists-include-keywords",
        action="store_true",
        help="Include keywords section when using --format lists",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    load_dotenv()
    if (args.openai_model or "").strip() in {"", "gpt-3.5-turbo"}:
        args.openai_model = (
            os.environ.get("OPENAI_MODEL")
            or os.environ.get("MODEL_NAME")
            or args.openai_model
        )
    if not args.accept_language:
        args.accept_language = os.environ.get("PIN_ACCEPT_LANGUAGE", "").strip()
    api_key = ""
    if args.openai:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            print(
                "Error: OPENAI_API_KEY is not set. Add it to .env or your environment.",
                file=sys.stderr,
            )
            return 2
    urls = collect_urls(args)
    if not urls:
        print("No URLs found. Provide pin URLs as args, a file, or stdin.", file=sys.stderr)
        return 2

    rows = []
    for url in urls:
        pin_id = extract_pin_id(url)
        title = ""
        visit_url = ""
        html_text = ""
        html_context = None

        api_data = fetch_pin_api(pin_id, args.timeout, args.accept_language)
        if api_data:
            title, visit_url = extract_fields_from_dict(api_data)

        if not title or not visit_url:
            resource_data = fetch_pin_resource(pin_id, args.timeout, args.accept_language)
            if resource_data:
                resource_title, resource_visit = extract_fields_from_dict(resource_data)
                if not title:
                    title = resource_title
                if not visit_url:
                    visit_url = resource_visit

        if args.openai or not title or not visit_url:
            try:
                status, html_text = fetch_url(url, args.timeout, args.accept_language)
            except urllib.error.URLError as exc:
                print(f"Fetch failed for {url}: {exc}", file=sys.stderr)
                html_text = ""
            if html_text:
                html_title, html_visit, html_context = extract_from_html(
                    html_text, pin_id, url
                )
                if not title:
                    title = html_title
                if not visit_url:
                    visit_url = html_visit

        site_recipe_name = ""
        site_title = ""
        site_description = ""
        if visit_url:
            site_recipe_name, site_title, site_description = extract_title_from_recipe_page(
                visit_url, args.timeout, args.accept_language
            )
            candidate_title = site_recipe_name or site_title
            candidate_title = normalize_recipe_title(candidate_title)
            if candidate_title:
                title = candidate_title
            elif title_looks_like_domain(title, visit_url) and site_title:
                title = normalize_recipe_title(site_title)

            if title_looks_like_domain(title, visit_url) or title_looks_like_person(title):
                slug_title = title_from_url_slug(visit_url)
                if slug_title:
                    title = normalize_recipe_title(slug_title)

        if html_context is None:
            html_context = {}
        if site_title:
            html_context["site_title"] = site_title
        if site_description:
            html_context["site_description"] = site_description
        if site_recipe_name:
            html_context["site_recipe_name"] = site_recipe_name

        openai_keywords = []
        if args.openai:
            context = html_context or {
                "pin_title": clean_title(title),
                "pin_description": "",
                "image_alt_text": "",
                "snippets": [],
            }
            openai_result = extract_with_openai(
                context,
                api_key,
                args.openai_model,
                args.openai_timeout,
                args.openai_temperature,
                args.openai_max_tokens,
            )
            if openai_result:
                if openai_result.get("recipe_name"):
                    title = openai_result["recipe_name"]
                if openai_result.get("keywords"):
                    openai_keywords = openai_result["keywords"]

        visit_url = unwrap_pinterest_redirect(visit_url)
        if visit_url and not is_external_url(visit_url):
            visit_url = ""

        title = normalize_recipe_title(clean_title(title))
        keywords = (
            ", ".join(openai_keywords) if openai_keywords else extract_keywords(title)
        )
        row = {
            "recipe": title.strip(),
            "keywords": keywords,
            "pinterest_url": url,
            "visit_site_url": visit_url,
        }
        rows.append(row)

    output_rows(
        rows,
        args.format,
        include_header=not args.no_header,
        lists_include_keywords=args.lists_include_keywords,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
