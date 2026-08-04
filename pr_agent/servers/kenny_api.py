# KENNY
"""Kenny JSON API: run PR-Agent tools in-process and return their output as JSON.

Every endpoint installs a request-scoped settings copy with publish_output=False
(see pr_agent.kenny.settings_context), so nothing here ever posts to GitHub.
Auth is a shared secret: X-Kenny-Key must equal env KENNY_API_KEY.
"""

import asyncio
import traceback
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pr_agent.config_loader import get_settings
from pr_agent.kenny.settings_context import UnknownProviderError, kenny_request_settings
from pr_agent.log import get_logger

router = APIRouter(prefix="/kenny/v1")


def require_api_key(request: Request):
    expected = os.environ.get("KENNY_API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="KENNY_API_KEY is not configured on the engine")
    if request.headers.get("X-Kenny-Key") != expected:
        raise HTTPException(status_code=401, detail="Invalid X-Kenny-Key")


class PRRequest(BaseModel):
    pr_url: str
    provider_id: Optional[str] = None


class AskRequest(PRRequest):
    question: str


class ExplainHunkRequest(PRRequest):
    file_name: str
    line_start: int
    line_end: int
    side: str = "RIGHT"
    diff_hunk: Optional[str] = None
    question: Optional[str] = None


class ProviderTestRequest(BaseModel):
    litellm_model: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    provider_id: Optional[str] = None  # resolve stored (encrypted) credentials server-side


def _as_int(value) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _validate_pr_url(pr_url: str):
    if "/pull/" not in pr_url and "/merge_requests/" not in pr_url and "/pull-requests/" not in pr_url:
        raise HTTPException(status_code=422, detail=f"Not a recognizable PR URL: {pr_url}")


def _setup(body: PRRequest):
    _validate_pr_url(body.pr_url)
    try:
        return kenny_request_settings(body.provider_id)
    except UnknownProviderError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _meta(settings, started: float) -> dict:
    return {
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "model_used": settings.config.model,
    }


def _tool_failure(op: str, e: Exception):
    # retry_with_fallback_models re-raises as a generic "failed with any model"
    # and chains the real cause, so walk __cause__ to the bottom — that's the
    # message that actually tells you what to fix.
    parts = []
    seen = set()
    cur: Optional[BaseException] = e
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        text = str(cur).strip()
        if text:
            label = type(cur).__name__
            parts.append(text if isinstance(cur, RuntimeError) else f"{label}: {text}")
        cur = cur.__cause__ or cur.__context__
    detail = " ← ".join(parts) or type(e).__name__
    get_logger().error(f"Kenny API {op} failed: {detail}",
                       artifact={"traceback": traceback.format_exc()})
    return HTTPException(status_code=502, detail=f"{op} failed — {detail}"[:2000])


@router.get("/health")
async def health():
    return {"status": "ok", "service": "kenny-engine"}


@router.post("/explain", dependencies=[Depends(require_api_key)])
async def explain(body: PRRequest):
    from pr_agent.tools.pr_description import PRDescription
    settings = _setup(body)
    started = time.monotonic()
    try:
        tool = PRDescription(body.pr_url)
        await tool.run()
    except HTTPException:
        raise
    except Exception as e:
        raise _tool_failure("explain", e)
    data = getattr(tool, "data", None)
    artifact = (getattr(settings, "data", None) or {}).get("artifact")
    if not data and not artifact:
        raise _tool_failure("explain", RuntimeError("model returned no output"))
    return {"data": data, "artifact": artifact, **_meta(settings, started)}


@router.post("/explain-hunk", dependencies=[Depends(require_api_key)])
async def explain_hunk(body: ExplainHunkRequest):
    from pr_agent.tools.pr_line_questions import PR_LineQuestions
    settings = _setup(body)
    settings.set("FILE_NAME", body.file_name)
    settings.set("LINE_START", body.line_start)
    settings.set("LINE_END", body.line_end)
    settings.set("SIDE", body.side)
    if body.diff_hunk:
        settings.set("ASK_DIFF_HUNK", body.diff_hunk)
    question = body.question or "Explain what this change does and why it matters."
    started = time.monotonic()
    try:
        tool = PR_LineQuestions(body.pr_url, args=[question])
        await tool.run()
    except HTTPException:
        raise
    except Exception as e:
        raise _tool_failure("explain-hunk", e)
    answer = (getattr(settings, "data", None) or {}).get("artifact")
    if not answer:
        raise _tool_failure("explain-hunk", RuntimeError("no answer produced (empty hunk match?)"))
    return {"answer": answer, **_meta(settings, started)}


@router.post("/review", dependencies=[Depends(require_api_key)])
async def review(body: PRRequest):
    from pr_agent.tools.pr_reviewer import PRReviewer
    settings = _setup(body)
    started = time.monotonic()
    try:
        tool = PRReviewer(body.pr_url)
        await tool.run()
    except HTTPException:
        raise
    except Exception as e:
        raise _tool_failure("review", e)
    artifact = (getattr(settings, "data", None) or {}).get("artifact")
    if not artifact:
        raise _tool_failure("review", RuntimeError("model returned no output"))
    parsed = (getattr(tool, "data", None) or {}).get("review", {})
    findings = []
    for issue in parsed.get("key_issues_to_review", []) or []:
        if not isinstance(issue, dict):
            continue
        severity = str(issue.get("severity", "") or "").strip().lower()
        findings.append({
            "file": str(issue.get("relevant_file", "") or "").strip(),
            "header": str(issue.get("issue_header", "") or "").strip(),
            "content": str(issue.get("issue_content", "") or "").strip(),
            "severity": severity if severity in ("critical", "high", "medium", "low") else "medium",
            "start_line": _as_int(issue.get("start_line")),
            "end_line": _as_int(issue.get("end_line")),
        })
    return {
        "artifact": artifact,
        "findings": findings,
        "effort": parsed.get("estimated_effort_to_review_[1-5]"),
        "security_concerns": parsed.get("security_concerns"),
        **_meta(settings, started),
    }


@router.post("/improve", dependencies=[Depends(require_api_key)])
async def improve(body: PRRequest):
    """Qodo's flagship: actionable code suggestions with before/after snippets."""
    from pr_agent.tools.pr_code_suggestions import PRCodeSuggestions
    settings = _setup(body)
    started = time.monotonic()
    try:
        tool = PRCodeSuggestions(body.pr_url)
        await tool.run()
    except HTTPException:
        raise
    except Exception as e:
        raise _tool_failure("improve", e)
    raw = (getattr(tool, "data", None) or {}).get("code_suggestions", []) or []
    suggestions = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        suggestions.append({
            "file": str(s.get("relevant_file", "") or "").strip(),
            "summary": str(s.get("one_sentence_summary", "") or "").strip(),
            "content": str(s.get("suggestion_content", "") or "").strip(),
            "existing_code": str(s.get("existing_code", "") or ""),
            "improved_code": str(s.get("improved_code", "") or ""),
            "label": str(s.get("label", "") or "").strip(),
            "score": _as_int(s.get("score")),
            "score_why": str(s.get("score_why", "") or "").strip(),
        })
    return {
        "suggestions": suggestions,
        "artifact": (getattr(settings, "data", None) or {}).get("artifact"),
        **_meta(settings, started),
    }


@router.post("/labels", dependencies=[Depends(require_api_key)])
async def labels(body: PRRequest):
    from pr_agent.tools.pr_generate_labels import PRGenerateLabels
    settings = _setup(body)
    started = time.monotonic()
    try:
        tool = PRGenerateLabels(body.pr_url)
        await tool.run()
    except HTTPException:
        raise
    except Exception as e:
        raise _tool_failure("labels", e)
    return {
        "labels": getattr(tool, "labels", []) or [],
        **_meta(settings, started),
    }


@router.post("/ask", dependencies=[Depends(require_api_key)])
async def ask(body: AskRequest):
    from pr_agent.tools.pr_questions import PRQuestions
    settings = _setup(body)
    started = time.monotonic()
    try:
        tool = PRQuestions(body.pr_url, args=[body.question])
        await tool.run()
    except HTTPException:
        raise
    except Exception as e:
        raise _tool_failure("ask", e)
    artifact = (getattr(settings, "data", None) or {}).get("artifact")
    if not artifact:
        raise _tool_failure("ask", RuntimeError("model returned no output"))
    return {"artifact": artifact, **_meta(settings, started)}


@router.post("/providers/test", dependencies=[Depends(require_api_key)])
async def providers_test(body: ProviderTestRequest):
    import litellm
    started = time.monotonic()
    kwargs = {
        "model": body.litellm_model,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "max_tokens": 10,
        "timeout": 20,
    }
    if body.provider_id and not body.api_key:
        from pr_agent.kenny.provider_store import get_provider, get_providers
        get_providers(force_refresh=True)  # the dashboard may have just saved it
        stored = get_provider(body.provider_id)
        if stored is None:
            raise HTTPException(status_code=422, detail=f"Unknown provider_id: {body.provider_id}")
        kwargs["model"] = stored.litellm_model
        if stored.api_base:
            kwargs["api_base"] = stored.api_base
        if stored.api_key:
            kwargs["api_key"] = stored.api_key
    if body.api_base:
        kwargs["api_base"] = body.api_base
    if body.api_key:
        kwargs["api_key"] = body.api_key
    try:
        await asyncio.wait_for(litellm.acompletion(**kwargs), timeout=25)
    except Exception as e:
        return {"ok": False, "latency_ms": int((time.monotonic() - started) * 1000), "error": str(e)}
    return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000), "error": None}
