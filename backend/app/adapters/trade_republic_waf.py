"""Acquire Trade Republic's AWS WAF token in a real JavaScript runtime.

The surrounding unofficial protocol integration was informed by the
MIT-licensed ``pytr`` project. See ``THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

WAF_URL = "https://app.traderepublic.com"
TOKEN_MAX_AGE_SECONDS = 3 * 60 * 60
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class WafToken:
    value: str
    created_at: float


_cached: WafToken | None = None
_lock = threading.Lock()


def get_waf_token(*, force_refresh: bool = False) -> str:
    global _cached
    with _lock:
        now = time.monotonic()
        if (
            not force_refresh
            and _cached is not None
            and now - _cached.created_at < TOKEN_MAX_AGE_SECONDS
        ):
            return _cached.value
        token = _run_challenge()
        _cached = WafToken(value=token, created_at=now)
        return token


def _run_challenge() -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Trade Republic login requires the configured Chromium runtime"
        ) from exc

    logger.info("Trade Republic: acquiring a fresh AWS WAF token")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = browser.new_context(user_agent=USER_AGENT, locale="de-DE")
            page = context.new_page()
            page.goto(WAF_URL, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_function(
                "() => window.AwsWafIntegration && "
                "typeof window.AwsWafIntegration.getToken === 'function'",
                timeout=45_000,
            )
            token = page.evaluate("async () => await window.AwsWafIntegration.getToken()")
            if not isinstance(token, str) or not token:
                token = next(
                    (
                        cookie["value"]
                        for cookie in context.cookies()
                        if cookie["name"] == "aws-waf-token"
                    ),
                    None,
                )
            if not isinstance(token, str) or not token:
                raise RuntimeError("Trade Republic WAF challenge returned no token")
            return token
        finally:
            browser.close()
