# KENNY
"""Kenny Jev-only JSON API: POST /kenny/v1/jev-check."""

from __future__ import annotations

import os
import time
import traceback
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pr_agent.kenny.jev_checks import partition_findings, run_jev_checks
from pr_agent.kenny.jev_client import (
    jev_commit_checks_enabled,
    jev_enabled,
    typesafe_api_key,
    typesafe_model,
)
from pr_agent.kenny.jev_diff import (
    fetch_commit_file_patches,
    fetch_pr_file_patches,
    parse_commit_url,
)
from pr_agent.kenny.jev_publish import publish_jev_commit_findings, publish_jev_pr_findings
from pr_agent.kenny.settings_context import UnknownProviderError, kenny_request_settings
from pr_agent.log import get_logger

router = APIRouter(prefix="/kenny/v1")


def require_api_key(request: Request):
    expected = os.environ.get("KENNY_API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="KENNY_API_KEY is not configured on the engine")
    if request.headers.get("X-Kenny-Key") != expected:
        raise HTTPException(status_code=401, detail="Invalid X-Kenny-Key")


class JevCheckRequest(BaseModel):
    pr_url: Optional[str] = None
    commit_url: Optional[str] = None
    owner: Optional[str] = None
    repo: Optional[str] = None
    commit_sha: Optional[str] = None
    publish: bool = False
    provider_id: Optional[str] = None


def _validate_pr_url(pr_url: str):
    if "/pull/" not in pr_url and "/merge_requests/" not in pr_url and "/pull-requests/" not in pr_url:
        raise HTTPException(status_code=422, detail=f"Not a recognizable PR URL: {pr_url}")


def _failure(op: str, e: Exception):
    get_logger().error(
        f"Kenny API {op} failed: {e}",
        artifact={"traceback": traceback.format_exc()},
    )
    return HTTPException(status_code=502, detail=f"{op} failed — {e}"[:2000])


@router.post("/jev-check", dependencies=[Depends(require_api_key)])
async def jev_check(body: JevCheckRequest):
    """Jev-only sanity checks on a PR diff and/or commit.

    Body: `{ pr_url?, commit_url?, owner?, repo?, commit_sha?, publish? }`
    Returns `{ findings, auto_commented, hints, elapsed_ms, model_used }`.
    """
    if not jev_enabled():
        raise HTTPException(
            status_code=503,
            detail="Jev is disabled (set TYPESAFE_API_KEY and/or JEV_ENABLED=true)",
        )
    if not typesafe_api_key():
        raise HTTPException(status_code=503, detail="TYPESAFE_API_KEY is not configured")

    try:
        kenny_request_settings(body.provider_id)
    except UnknownProviderError as e:
        raise HTTPException(status_code=422, detail=str(e))

    started = time.monotonic()
    file_patches: list[dict] = []
    git_provider = None
    owner, repo, commit_sha = body.owner, body.repo, body.commit_sha

    if body.commit_url and not (owner and repo and commit_sha):
        owner, repo, commit_sha = parse_commit_url(body.commit_url)

    if body.pr_url:
        _validate_pr_url(body.pr_url)
        try:
            file_patches, git_provider = fetch_pr_file_patches(body.pr_url)
        except Exception as e:
            raise _failure("jev-check", e)
    elif owner and repo and commit_sha:
        if not jev_commit_checks_enabled():
            raise HTTPException(status_code=503, detail="JEV_COMMIT_CHECKS is disabled")
        try:
            file_patches = fetch_commit_file_patches(owner, repo, commit_sha)
        except Exception as e:
            raise _failure("jev-check", e)
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide pr_url, or commit_url, or owner+repo+commit_sha",
        )

    try:
        model_used = typesafe_model()
        findings = await run_jev_checks(file_patches, model=model_used)
    except Exception as e:
        raise _failure("jev-check", e)

    parts = partition_findings(findings)
    published = None
    if body.publish and parts["auto_commented"]:
        try:
            if git_provider is not None:
                published = publish_jev_pr_findings(git_provider, parts["auto_commented"])
            elif owner and repo and commit_sha:
                from pr_agent.git_providers.github_provider import GithubProvider
                gh = GithubProvider()
                published = publish_jev_commit_findings(
                    gh.github_client, owner, repo, commit_sha, parts["auto_commented"]
                )
        except Exception as e:
            get_logger().error(f"Kenny Jev publish failed: {e}")
            published = {"error": str(e)}

    return {
        "findings": findings,
        "auto_commented": parts["auto_commented"],
        "hints": parts["hints"],
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "model_used": model_used,
        "published": published,
        "files_scanned": len(file_patches),
    }
