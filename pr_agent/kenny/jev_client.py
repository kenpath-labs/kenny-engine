# KENNY
"""Thin TypeSafe / Jev client wrapper for Kenny System One checks.

Reads TYPESAFE_API_KEY and TYPESAFE_MODEL (default jev-latest). Prefer the async
client when the FastAPI handlers are async; sync helpers run in a worker thread.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Mapping, Optional

DEFAULT_MODEL = "jev-latest"


def typesafe_api_key() -> Optional[str]:
    return (os.environ.get("TYPESAFE_API_KEY") or "").strip() or None


def typesafe_model() -> str:
    return (os.environ.get("TYPESAFE_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def jev_enabled() -> bool:
    """JEV_ENABLED defaults to true when TYPESAFE_API_KEY is set."""
    raw = os.environ.get("JEV_ENABLED")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return typesafe_api_key() is not None


def jev_commit_checks_enabled() -> bool:
    if not jev_enabled():
        return False
    raw = os.environ.get("JEV_COMMIT_CHECKS", "true")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def jev_pr_cascade_enabled() -> bool:
    if not jev_enabled():
        return False
    raw = os.environ.get("JEV_PR_CASCADE", "true")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _client_kwargs() -> dict:
    kwargs: dict[str, Any] = {}
    key = typesafe_api_key()
    if key:
        kwargs["api_key"] = key
    return kwargs


async def system_one_async(
    state: Any,
    questions: Mapping[str, Any],
    model: Optional[str] = None,
) -> Any:
    """Run System One via AsyncTypeSafeClient."""
    from typesafe_sdk import AsyncTypeSafeClient

    used_model = model or typesafe_model()
    async with AsyncTypeSafeClient(**_client_kwargs()) as client:
        return await client.system_one(state=state, questions=questions, model=used_model)


def system_one_sync(
    state: Any,
    questions: Mapping[str, Any],
    model: Optional[str] = None,
) -> Any:
    """Run System One via sync TypeSafeClient."""
    from typesafe_sdk import TypeSafeClient

    used_model = model or typesafe_model()
    with TypeSafeClient(**_client_kwargs()) as client:
        return client.system_one(state=state, questions=questions, model=used_model)


async def system_one(
    state: Any,
    questions: Mapping[str, Any],
    model: Optional[str] = None,
) -> Any:
    """Prefer async client; fall back to sync in a thread if import fails."""
    try:
        return await system_one_async(state, questions, model=model)
    except ImportError:
        return await asyncio.to_thread(system_one_sync, state, questions, model)
