"""
extractors/ai_backstop.py — AI-powered selector resilience layer.

Provides resilient DOM element finding with LLM fallback:
  1. Try each CSS selector in a cascade (fast, free)
  2. If ALL fail, ask an LLM to find the correct selector (slow, metered)

Code-first philosophy: the AI is a safety net, NOT the primary strategy.
During normal operation, step 1 succeeds and the AI is never called.

When the AI *does* fire it returns a structured JSON response with:
  - quick_fix_selector: used immediately to unblock the current run
  - enduring_selector:  auto-patched into selector_registry.yaml
  - diagnostic:         human-readable explanation of what changed
  - confidence:         1-100 score; suggestions below 70 are rejected

All repairs are appended to logs/ai_repairs.jsonl for human review.

Usage:
    from extractors.ai_backstop import resilient_find, load_selectors

    registry = load_selectors()
    el = resilient_find(page, registry["nfcu"]["login"]["username"])
"""

import hashlib
import json
import logging
import os
import re
import time
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("sentry.extractors.ai_backstop")

# ── Paths ────────────────────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = _THIS_DIR / "selector_registry.yaml"
CACHE_DIR = _THIS_DIR.parent / ".ai_cache"
REPAIR_LOG_PATH = _THIS_DIR.parent / "logs" / "ai_repairs.jsonl"

# ── Cost controls ────────────────────────────────────────────────────────────
MAX_AI_CALLS_PER_RUN = 5
_ai_calls_this_run = 0

# ── Session cache (in-memory, reset per-run) ─────────────────────────────────
_session_cache: dict[str, str] = {}


# ── Registry I/O ─────────────────────────────────────────────────────────────


def load_selectors() -> dict:
    """Load the selector registry YAML."""
    if not REGISTRY_PATH.exists():
        log.error("Selector registry not found: %s", REGISTRY_PATH)
        return {}
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_selectors(registry: dict):
    """Write the selector registry back to disk."""
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        yaml.dump(
            registry,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )


def get_selector_group(registry: dict, path: str) -> dict | None:
    """Navigate the registry by dot-separated path.

    Example: get_selector_group(reg, "nfcu.login.username")
    Returns: {"intent": "...", "selectors": [...]}
    """
    node = registry
    for key in path.split("."):
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return None
    return node if isinstance(node, dict) and "selectors" in node else None


# ── Core: Resilient Find ─────────────────────────────────────────────────────


def resilient_find(
    page,
    selector_group: dict,
    template_vars: dict | None = None,
    timeout: float = 0,
    allow_ai: bool = True,
) -> Any | None:
    """Try each CSS selector in order. If ALL fail, ask the AI.

    Args:
        page: Playwright Page (or Frame) object.
        selector_group: Dict with 'intent' and 'selectors' keys
                        (from selector_registry.yaml).
        template_vars: Optional dict for f-string expansion in selectors,
                       e.g. {"name": "Checking", "last4": "1234"}.
        timeout: Seconds to wait for element visibility (0 = instant check).
        allow_ai: If False, skip the AI fallback (useful for fast checks).

    Returns:
        ElementHandle if found (by code or AI), None if everything fails.
    """
    intent = selector_group.get("intent", "unknown element")
    selectors = selector_group.get("selectors", [])

    # Expand template variables in selectors
    if template_vars:
        selectors = [_expand_template(s, template_vars) for s in selectors]

    # ── Phase 1: Code-first — try every selector (fast, free) ────────
    # Check all instantly first
    for sel in selectors:
        if el := _try_selector(page, sel, timeout=0):
            return el

    # If timeout provided, poll for ANY of them to appear
    if timeout > 0:
        end_time = time.time() + timeout
        while time.time() < end_time:
            for sel in selectors:
                if el := _try_selector(page, sel, timeout=0):
                    return el
            time.sleep(0.5)

    # ── Phase 2: AI backstop — only if ALL selectors failed ──────────
    log.warning("All %d selectors failed for: %s", len(selectors), intent)
    if allow_ai:
        return _ai_fallback(page, selectors, intent)
    return None


def resilient_fill(
    page,
    selector_group: dict,
    value: str,
    template_vars: dict | None = None,
    verify: bool = True,
) -> bool:
    """Find an input element resiliently and fill it with a value.

    Combines resilient_find with click → clear → fill → verify.

    Returns:
        True if the value was successfully filled and verified.
    """
    el = resilient_find(page, selector_group, template_vars)
    if not el:
        return False

    try:
        el.click()
        page.wait_for_timeout(300)
        el.fill("")
        el.fill(value)
        page.wait_for_timeout(300)

        if verify:
            actual = el.input_value()
            if actual != value:
                log.warning(
                    "Fill succeeded but value didn't stick for: %s",
                    selector_group.get("intent", "?"),
                )
                return False

        log.info("Filled: %s", selector_group.get("intent", "?"))
        return True
    except Exception as e:
        log.warning("Error filling element: %s", e)
        return False


def resilient_click(
    page,
    selector_group: dict,
    template_vars: dict | None = None,
    allow_ai: bool = True,
) -> bool:
    """Find an element resiliently and click it.

    Returns:
        True if clicked successfully.
    """
    el = resilient_find(page, selector_group, template_vars, allow_ai=allow_ai)
    if not el:
        return False

    try:
        el.click()
        log.info("Clicked: %s", selector_group.get("intent", "?"))
        return True
    except Exception as e:
        log.warning("Error clicking element: %s", e)
        return False


# ── Private Helpers ──────────────────────────────────────────────────────────


def _try_selector(page, selector: str, timeout: float = 0) -> Any | None:
    """Try a single CSS selector against the page."""
    try:
        if timeout > 0:
            page.wait_for_selector(selector, timeout=timeout * 1000, state="visible")
        el = page.query_selector(selector)
        if el and el.is_visible():
            return el
    except Exception as e:
        log.debug("Ignored exception: %s", e)
    return None


def _expand_template(selector: str, vars: dict) -> str:
    """Expand {name}, {last4}, etc. in a selector template."""
    try:
        return selector.format(**vars)
    except (KeyError, ValueError):
        return selector


# ── DOM Minification ─────────────────────────────────────────────────────────


def _minify_dom(page) -> str:
    """Aggressively minify the page DOM for the LLM.

    Strips invisible/decorative elements, redacts PII in non-interactive
    text, and hard-caps at 12 KB to stay within context limits while
    maximising signal-to-noise ratio.
    """
    from bs4 import BeautifulSoup

    try:
        raw_html = page.content()
    except Exception:
        return "<html>Could not extract HTML</html>"

    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove invisible, functional, and decorative noise
    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "img",
            "meta",
            "link",
            "iframe",
            "path",
            "picture",
            "source",
            "video",
        ]
    ):
        tag.decompose()

    # Remove explicitly hidden elements
    for tag in soup.find_all(style=re.compile(r"display:\s*none|visibility:\s*hidden")):
        tag.decompose()

    # Redact text in non-interactive elements to protect PII
    _KEEP_TEXT_TAGS = frozenset(
        [
            "button",
            "a",
            "label",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "input",
            "select",
            "option",
            "th",
            "legend",
            "summary",
        ]
    )
    for text_node in soup.find_all(string=True):
        parent = text_node.parent
        if parent and parent.name not in _KEEP_TEXT_TAGS:
            stripped = text_node.strip()
            if stripped and len(stripped) > 2:
                text_node.replace_with("[…]")

    # PII redaction on remaining text
    result = str(soup.body) if soup.body else str(soup)
    result = re.sub(r"\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?", "$X", result)
    result = re.sub(r"\b\d{5,}\b", "[REDACTED]", result)

    return result[:12000]


# ── AI Fallback ──────────────────────────────────────────────────────────────


def _ai_fallback(page, failed_selectors: list[str], intent: str) -> Any | None:
    """Use an LLM to find the correct CSS selector when all else fails.

    Flow:
      1. Check session cache (free, instant)
      2. Check rate limit (max 5 calls per run)
      3. Check file cache (avoid re-asking for same page + intent)
      4. Minify the DOM and send to Gemini
      5. Parse the structured JSON response
      6. Validate quick_fix against live DOM
      7. If confidence >= 70: cache, log repair, auto-patch registry
    """
    global _ai_calls_this_run

    # ── 1. Session cache (zero cost, in-memory) ──────────────────────
    session_key = _cache_key(page.url, intent)
    if session_key in _session_cache:
        cached_sel = _session_cache[session_key]
        log.info("Session cache hit for: %s → %s", intent, cached_sel)
        el = _try_selector(page, cached_sel)
        if el:
            return el
        log.info("Session-cached selector stale, continuing")

    # ── 2. Rate limit ────────────────────────────────────────────────
    if _ai_calls_this_run >= MAX_AI_CALLS_PER_RUN:
        log.warning(
            "AI backstop rate limit reached (%d/%d). Skipping.",
            _ai_calls_this_run,
            MAX_AI_CALLS_PER_RUN,
        )
        return None

    # ── 3. File cache ────────────────────────────────────────────────
    cached = _load_cache(session_key)
    if cached:
        log.info("AI backstop file-cache hit for: %s", intent)
        el = _try_selector(page, cached)
        if el:
            _session_cache[session_key] = cached
            return el
        log.info("File-cached selector no longer works, re-querying AI")

    # ── 4. Call Gemini ───────────────────────────────────────────────
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        log.warning("GEMINI_API_KEY not set — AI backstop disabled")
        return None

    _ai_calls_this_run += 1
    log.info(
        "AI backstop call %d/%d for: %s",
        _ai_calls_this_run,
        MAX_AI_CALLS_PER_RUN,
        intent,
    )

    minified_html = _minify_dom(page)
    fix = _call_gemini(api_key, minified_html, intent, failed_selectors)
    if not fix:
        return None

    # ── 5. Confidence gate ───────────────────────────────────────────
    confidence = fix.get("confidence", 0)
    quick = fix.get("quick_fix_selector", "")
    enduring = fix.get("enduring_selector", "")
    diagnostic = fix.get("diagnostic", "")

    if confidence < 70:
        log.warning(
            "AI confidence too low (%d) for '%s'. Rejecting.",
            confidence,
            intent,
        )
        return None

    # ── 6. Validate quick_fix against live DOM ───────────────────────
    el = _try_selector(page, quick) if quick else None
    # If quick_fix fails, try enduring as fallback
    if not el and enduring:
        el = _try_selector(page, enduring)
        if el:
            quick = enduring  # Use the one that actually worked

    if el:
        log.info(
            "AI backstop healed '%s' → %s (confidence=%d)",
            intent,
            quick,
            confidence,
        )
        # Cache for the rest of this run
        _session_cache[session_key] = quick
        _save_cache(session_key, quick)

        # Log the repair for human review
        _log_repair(
            intent=intent,
            failed=failed_selectors,
            quick_fix=quick,
            enduring=enduring,
            diagnostic=diagnostic,
            confidence=confidence,
            url=page.url,
        )

        # Auto-patch the registry with the enduring selector
        if enduring:
            _auto_patch_registry(intent, enduring)

        return el

    log.warning(
        "AI suggestions did not match live DOM: quick=%s, enduring=%s",
        quick,
        enduring,
    )
    return None


def _call_gemini(
    api_key: str, html: str, intent: str, failed: list[str]
) -> dict | None:
    """Send a structured selector-finding prompt to Gemini.

    Returns a dict with keys: confidence, quick_fix_selector,
    enduring_selector, diagnostic.  Returns None on failure.
    """
    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        prompt = f"""You are a CSS/Playwright selector expert analysing a live financial-institution page.

TASK: Find selectors for this element.

INTENT: {intent}

FAILED SELECTORS (all broken):
{json.dumps(failed, indent=2)}

MINIFIED DOM:
```html
{html}
```

Return ONLY a JSON object with these exact keys:
{{
  "confidence": <int 1-100>,
  "quick_fix_selector": "<CSS or Playwright selector that matches the element RIGHT NOW>",
  "enduring_selector": "<robust selector using stable attributes like aria-label, data-testid, name, role>",
  "diagnostic": "<one-sentence explanation of what changed on the site>"
}}

Rules:
- Each selector must match exactly ONE visible element
- Prefer Playwright-extended selectors (e.g. :has-text(), text=) when pure CSS can't express the intent
- The enduring_selector should survive site reskins by using stable attributes
- Return raw JSON only — no markdown fences, no commentary"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        raw = response.text.strip()
        # Strip markdown code fences if the model wrapped the JSON
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        fix = json.loads(raw)
        log.info(
            "Gemini response: confidence=%s quick=%s enduring=%s diag=%s",
            fix.get("confidence"),
            fix.get("quick_fix_selector"),
            fix.get("enduring_selector"),
            fix.get("diagnostic", "")[:80],
        )
        return fix

    except json.JSONDecodeError as e:
        log.error("Gemini returned non-JSON: %s — raw: %s", e, raw[:200])
        return None
    except Exception as e:
        log.error("Gemini API error: %s", e)
        return None


# ── Cache ────────────────────────────────────────────────────────────────────


def _cache_key(url: str, intent: str) -> str:
    """Generate a deterministic cache key from URL domain + intent."""
    from urllib.parse import urlparse

    domain = urlparse(url).netloc
    raw = f"{domain}|{intent}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _load_cache(key: str) -> str | None:
    """Load a cached AI selector result."""
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            return data.get("selector")
        except Exception as e:
            log.debug("Ignored exception: %s", e)
    return None


def _save_cache(key: str, selector: str):
    """Save an AI selector result to the local cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{key}.json"
    data = {"selector": selector, "cached_at": datetime.now().isoformat()}
    cache_file.write_text(json.dumps(data, indent=2))


# ── Repair Log (append-only JSONL) ───────────────────────────────────────────


def _log_repair(
    intent: str,
    failed: list[str],
    quick_fix: str,
    enduring: str,
    diagnostic: str,
    confidence: int,
    url: str,
):
    """Append a structured repair entry to logs/ai_repairs.jsonl.

    This file is the human-reviewable audit trail.  Each line is a
    self-contained JSON object that can be grepped, tailed, or piped
    into a dashboard.
    """
    entry = {
        "ts": datetime.now().isoformat(),
        "intent": intent,
        "url": url,
        "failed": failed,
        "quick_fix": quick_fix,
        "enduring": enduring,
        "diagnostic": diagnostic,
        "confidence": confidence,
    }
    REPAIR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPAIR_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    log.info("Repair logged → %s", REPAIR_LOG_PATH.name)


# ── Auto-Patch Registry ──────────────────────────────────────────────────────


def _auto_patch_registry(intent: str, enduring_selector: str):
    """Prepend the enduring selector to the matching group in the YAML.

    Walks the registry tree looking for a group whose 'intent' matches,
    then inserts the new selector at position 0 (highest priority).
    On the next run the code-first path picks it up for free.
    """
    registry = load_selectors()
    if not registry:
        return

    patched = _patch_walk(registry, intent, enduring_selector)
    if patched:
        save_selectors(registry)
        log.info(
            "Auto-patched registry: '%s' ← %s",
            intent,
            enduring_selector,
        )
    else:
        log.warning(
            "Could not find intent '%s' in registry to auto-patch",
            intent,
        )


def _patch_walk(node: dict, intent: str, selector: str) -> bool:
    """Recursively walk the registry and patch the matching group."""
    if isinstance(node, dict) and "selectors" in node and node.get("intent") == intent:
        sels = node["selectors"]
        if selector not in sels:
            sels.insert(0, selector)
        return True

    if isinstance(node, dict):
        for value in node.values():
            if isinstance(value, dict) and _patch_walk(value, intent, selector):
                return True
    return False


def reset_ai_counter():
    """Reset the per-run AI call counter and session cache.

    Called at the start of each connector run.
    """
    global _ai_calls_this_run, _session_cache
    _ai_calls_this_run = 0
    _session_cache = {}
