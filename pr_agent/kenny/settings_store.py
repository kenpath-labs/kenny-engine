# KENNY
"""Read-only access to the `review_settings` table managed by the dashboard.

Row with repo IS NULL is the global default; a row matching 'owner/name' overrides
it. Everything degrades to the shipped defaults when the DB or table is missing,
so the webhook keeps working before the dashboard is ever opened.
"""

import os
import time
from dataclasses import dataclass
from typing import Optional

def _log():
    """Lazy logger import — pr_agent.log pulls in config_loader, so importing it
    at module scope makes this module unsafe to import early."""
    from pr_agent.log import get_logger
    return get_logger()



_CACHE_TTL_SECONDS = 30

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass
class ReviewSettings:
    enabled: bool = True
    auto_review_on_open: bool = True
    review_on_push: bool = False
    auto_describe: bool = True
    auto_improve: bool = False
    comment_style: str = "summary_inline"  # summary | inline | summary_inline
    inline_severity_threshold: str = "medium"
    custom_instructions: str = ""
    allow_comment_commands: bool = True
    allow_publish: bool = True


_cache: dict = {"at": 0.0, "rows": None}


def _load_rows() -> dict:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return {}
    try:
        import psycopg
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            rows = conn.execute(
                "SELECT repo, enabled, auto_review_on_open, review_on_push, auto_describe,"
                "       auto_improve, comment_style, inline_severity_threshold, custom_instructions, allow_comment_commands, allow_publish"
                "  FROM review_settings"
            ).fetchall()
    except Exception as e:
        _log().warning(f"Kenny settings store unavailable: {e}")
        return {}
    out = {}
    for r in rows:
        out[r[0]] = ReviewSettings(
            enabled=bool(r[1]),
            auto_review_on_open=bool(r[2]),
            review_on_push=bool(r[3]),
            auto_describe=bool(r[4]),
            auto_improve=bool(r[5]),
            comment_style=r[6] or "summary_inline",
            inline_severity_threshold=r[7] or "medium",
            custom_instructions=r[8] or "",
            allow_comment_commands=bool(r[9]),
            allow_publish=bool(r[10]),
        )
    return out


def _rows(force_refresh: bool = False) -> dict:
    now = time.monotonic()
    if force_refresh or _cache["rows"] is None or now - _cache["at"] > _CACHE_TTL_SECONDS:
        _cache["rows"] = _load_rows()
        _cache["at"] = now
    return _cache["rows"]


def get_settings_for_repo(repo: Optional[str]) -> ReviewSettings:
    """Most specific configuration wins: repo -> org -> instance default.

    `repo` is "owner/name"; the dashboard stores an org-wide row under the bare
    owner, and the instance-wide fallback under NULL.
    """
    rows = _rows()
    if repo:
        if repo in rows:
            return rows[repo]
        org = repo.split("/")[0]
        if org in rows:
            return rows[org]
    return rows.get(None) or ReviewSettings()


def apply_review_settings(settings, cfg: ReviewSettings) -> None:
    """Mutate a request-scoped settings object to match the dashboard configuration."""
    settings.set("PR_REVIEWER.PERSISTENT_COMMENT", cfg.comment_style != "inline")
    # 'inline' means findings ride on the diff instead of a summary table
    settings.set("PR_REVIEWER.INLINE_CODE_COMMENTS", cfg.comment_style != "summary")
    if cfg.custom_instructions:
        settings.set("PR_REVIEWER.EXTRA_INSTRUCTIONS", cfg.custom_instructions)
        settings.set("PR_DESCRIPTION.EXTRA_INSTRUCTIONS", cfg.custom_instructions)
        settings.set("PR_CODE_SUGGESTIONS.EXTRA_INSTRUCTIONS", cfg.custom_instructions)


def auto_commands(cfg: ReviewSettings) -> list[str]:
    """The /commands the webhook should run when a PR opens."""
    if not cfg.enabled or not cfg.auto_review_on_open:
        return []
    commands = []
    if cfg.auto_describe:
        commands.append("/describe --pr_description.final_update_message=false")
    commands.append("/review")
    if cfg.auto_improve:
        commands.append("/improve")
    return commands
