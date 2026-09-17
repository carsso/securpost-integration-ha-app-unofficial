"""Securpost API client package."""

from __future__ import annotations

import httpx

from custom_components.securpost_app.const import API_BASE_URL, APP_ORIGIN

REQUEST_TIMEOUT_SECONDS = 30


def create_http_client() -> httpx.AsyncClient:
    """Open a pool with its own cookie jar, which carries the better-auth session."""
    return httpx.AsyncClient(
        base_url=API_BASE_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"Accept": "application/json", "Origin": APP_ORIGIN},
    )
