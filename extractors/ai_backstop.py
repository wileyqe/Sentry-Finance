"""
extractors/ai_backstop.py — AI-powered selector resilience layer.

Provides resilient DOM element finding with LLM fallback:
  1. Try each CSS selector in a cascade (fast, free)
  2. If ALL fail, ask an LLM to find the correct selector (slow, metered)

Code-first philosophy: the AI is a safety net, NOT the primary strategy.
During normal operation, step 1 succeeds and the AI is never called.

Usage:
    from extractors.ai_backstop import resilient_find, load_selectors

    registry = load_selectors()
    el = resilient_find(page, registry["nfcu"]["login"]["username"])
"""

import hashlib
import json
import logging
import os
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
HEAL_LOG_PATH = _THIS_DIR.parent / "dom_health_report.json"

# ── Cost controls ────────────────────────────────────────────────────────────
MAX_AI_CALLS_PER_RUN = 5
_ai_calls_this_run = 0


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


# ── AI Fallback ──────────────────────────────────────────────────────────────


def _ai_fallback(page, failed_selectors: list[str], intent: str) -> Any | None:
    """Use an LLM to find the correct CSS selector when all else fails.

    Flow:
      1. Check rate limit (max 5 calls per run)
      2. Check local cache (avoid re-asking for same page+intent)
      3. Extract relevant HTML from the page
      4. Send to Gemini with the intent + failed selectors
      5. Validate the returned selector against the live DOM
      6. Cache the result and log for future healing
    """
    global _ai_calls_this_run

    if _ai_calls_this_run >= MAX_AI_CALLS_PER_RUN:
        log.warning(
            "AI backstop rate limit reached (%d/%d). Skipping.",
            _ai_calls_this_run,
            MAX_AI_CALLS_PER_RUN,
        )
        return None

    # Check cache
    cache_key = _cache_key(page.url, intent)
    cached = _load_cache(cache_key)
    if cached:
        log.info("AI backstop cache hit for: %s", intent)
        el = _try_selector(page, cached)
        if el:
            return el
        log.info("Cached selector no longer works, re-querying AI")

    # Extract relevant HTML (truncated)
    html_snippet = _extract_relevant_html(page, intent)

    # Call the LLM
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

    suggested_selector = _call_gemini(api_key, html_snippet, intent, failed_selectors)
    if not suggested_selector:
        return None

    # Validate against live DOM
    el = _try_selector(page, suggested_selector)
    if el:
        log.info("AI backstop found working selector: %s", suggested_selector)
        _save_cache(cache_key, suggested_selector)
        _log_heal(intent, failed_selectors, suggested_selector, page.url)
        return el

    log.warning("AI suggestion did not match live DOM: %s", suggested_selector)
    return None


def _call_gemini(api_key: str, html: str, intent: str, failed: list[str]) -> str | None:
    """Send a selector-finding prompt to Gemini."""
    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        prompt = f"""You are a CSS selector expert. Given the HTML below, find a single CSS selector for this element:

INTENT: {intent}

These selectors were tried but ALL FAILED:
{json.dumps(failed, indent=2)}

HTML (truncated):
```html
{html}
```

Rules:
- Return ONLY the CSS selector string, nothing else
- Prefer stable attributes (name, aria-label, data-testid, role) over dynamic IDs
- The selector must match exactly ONE visible element
- Do NOT wrap in quotes or backticks"""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )

        selector = response.text.strip().strip('"').strip("'").strip("`")
        log.info("Gemini suggested: %s", selector)
        return selector if selector else None

    except Exception as e:
        log.error("Gemini API error: %s", e)
        return None


def _sanitize_html_payload(html: str) -> str:
    """Sanitize HTML to prevent leaking PII or financial data to LLM."""
    import re

    # Mask dollar amounts (e.g., $1,234.56 -> $XX.XX)
    html = re.sub(r"\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?", "$XX.XX", html)
    # Mask consecutive digits of 5 or more (e.g., Account numbers)
    html = re.sub(r"\b\d{5,}\b", "[REDACTED]", html)
    return html


def _extract_relevant_html(page, intent: str) -> str:
    """Extract a truncated, relevant chunk of page HTML.

    Tries to find the most relevant container (form, main content)
    rather than sending the entire page.
    """
    try:
        # Try to get just the form or main content area
        for container_sel in [
            "form",
            "main",
            "[role='main']",
            "#content",
            ".login",
            "#login",
        ]:
            try:
                el = page.query_selector(container_sel)
                if el:
                    html = el.inner_html()
                    if len(html) > 200:  # Must be substantive
                        return _sanitize_html_payload(html[:4000])
            except Exception:
                continue

        # Fallback: body HTML truncated
        html = page.content()
        return _sanitize_html_payload(html[:4000])
    except Exception:
        return "<html>Could not extract HTML</html>"


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


# ── Heal Log ─────────────────────────────────────────────────────────────────


def _log_heal(intent: str, failed: list[str], fixed: str, url: str):
    """Append a healing event to the health report."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "intent": intent,
        "url": url,
        "failed_selectors": failed,
        "ai_selector": fixed,
    }

    report = []
    if HEAL_LOG_PATH.exists():
        try:
            report = json.loads(HEAL_LOG_PATH.read_text())
        except Exception as e:
            log.debug("Ignored exception: %s", e)

    report.append(entry)
    HEAL_LOG_PATH.write_text(json.dumps(report, indent=2))
    log.info("Logged healing event for: %s", intent)


def reset_ai_counter():
    """Reset the per-run AI call counter. Called at the start of each run."""
    global _ai_calls_this_run
    _ai_calls_this_run = 0
