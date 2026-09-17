# KENNY
"""Jev-first cascade helpers for /kenny/v1/review."""

from __future__ import annotations

import traceback
from typing import Any, Optional

from pr_agent.kenny.jev_checks import format_hints_for_llm, partition_findings, run_jev_checks
from pr_agent.kenny.jev_client import jev_enabled, jev_pr_cascade_enabled, typesafe_model
from pr_agent.kenny.jev_diff import fetch_pr_file_patches
from pr_agent.kenny.jev_publish import publish_jev_pr_findings
from pr_agent.log import get_logger


def inject_jev_hints_into_settings(settings, hints: list[dict]) -> None:
    """Append a short structured Jev block to pr_reviewer.extra_instructions."""
    block = format_hints_for_llm(hints)
    if not block:
        return
    existing = ""
    try:
        existing = settings.pr_reviewer.extra_instructions or ""
    except Exception:
        existing = ""
    merged = (existing.rstrip() + "\n\n" + block).strip() if existing else block
    settings.set("PR_REVIEWER.EXTRA_INSTRUCTIONS", merged)
    data = getattr(settings, "data", None) or {}
    if not isinstance(data, dict):
        data = {}
    data["jev_hints"] = hints
    settings.data = data


async def maybe_run_jev_cascade(
    *,
    pr_url: str,
    settings,
    skip_jev: bool = False,
    publish: bool = False,
    inline: bool = True,
) -> dict[str, Any]:
    """Run Jev before LLM review. Soft-fails to empty findings on error."""
    empty = {
        "jev_findings": [],
        "jev_auto_commented": [],
        "jev_hints": [],
        "jev_published": None,
        "jev_model_used": None,
    }
    if skip_jev or not jev_enabled() or not jev_pr_cascade_enabled():
        return empty

    try:
        file_patches, git_provider = fetch_pr_file_patches(pr_url)
        model = typesafe_model()
        findings = await run_jev_checks(file_patches, model=model)
        parts = partition_findings(findings)
        published = None
        if publish and parts["auto_commented"]:
            try:
                published = publish_jev_pr_findings(
                    git_provider, parts["auto_commented"], inline=inline
                )
            except Exception as e:
                get_logger().error(f"Kenny Jev pre-publish failed: {e}")
                published = {"error": str(e)}
        inject_jev_hints_into_settings(settings, parts["hints"])
        data_bag = getattr(settings, "data", None) or {}
        if not isinstance(data_bag, dict):
            data_bag = {}
        data_bag["jev_findings"] = findings
        settings.data = data_bag
        return {
            "jev_findings": findings,
            "jev_auto_commented": parts["auto_commented"],
            "jev_hints": parts["hints"],
            "jev_published": published,
            "jev_model_used": model,
        }
    except Exception as e:
        get_logger().error(
            f"Kenny Jev cascade skipped due to error: {e}",
            artifact={"traceback": traceback.format_exc()},
        )
        return empty
