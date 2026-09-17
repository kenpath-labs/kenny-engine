# KENNY
"""Jev (TypeSafe System One) structured sanity checks over file patches.

Builds state from `{path, language?, patch}`, asks parallel Noul + Score
questions for the high-risk rules, and routes findings by env thresholds:
  JEV_AUTO_COMMENT_MIN (default 0.85) → action=auto_comment
  JEV_HINT_MIN (default 0.55)         → action=hint_for_llm
  below hint                          → action=ignore
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterable, Optional

from pr_agent.kenny.jev_client import system_one, typesafe_model

# rule_id → (noul instructions, score instructions, default severity label)
RULE_SPECS: dict[str, dict[str, str]] = {
    "secrets_or_credentials": {
        "noul": (
            "Does this patch introduce hardcoded secrets, API keys, tokens, "
            "passwords, private keys, or other credentials that should not be committed?"
        ),
        "score": "How severe is the secrets/credentials risk in this patch?",
        "header": "Possible secrets or credentials",
        "severity": "critical",
    },
    "dangerous_destructive_ops": {
        "noul": (
            "Does this patch introduce dangerous or destructive operations "
            "(e.g. rm -rf, DROP TABLE, force-push, wiping storage, irreversible data loss)?"
        ),
        "score": "How severe is the destructive-operation risk in this patch?",
        "header": "Dangerous or destructive operation",
        "severity": "high",
    },
    "auth_or_payments_touch": {
        "noul": (
            "Does this patch touch authentication, authorization, session handling, "
            "or payment / billing / money-movement code paths?"
        ),
        "score": "How sensitive is the auth/payments surface touched by this patch?",
        "header": "Auth or payments surface touched",
        "severity": "high",
    },
    "missing_tests_for_api_surface": {
        "noul": (
            "Does this patch change a public API / HTTP / RPC surface without adding "
            "or updating corresponding tests?"
        ),
        "score": "How concerning is the missing-test gap for the API surface in this patch?",
        "header": "Missing tests for API surface",
        "severity": "medium",
    },
    "pii_exposure": {
        "noul": (
            "Does this patch risk exposing PII (emails, phone numbers, SSNs, addresses, "
            "personal identifiers) in logs, responses, commits, or client-visible data?"
        ),
        "score": "How severe is the PII exposure risk in this patch?",
        "header": "Possible PII exposure",
        "severity": "high",
    },
}

SCORE_LEVELS = [
    "none / not applicable",
    "low concern",
    "moderate concern",
    "high concern",
    "critical / must address",
]

_SEVERITY_FROM_SCORE = {
    0: "low",
    1: "low",
    2: "medium",
    3: "high",
    4: "critical",
}

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", re.M)


def auto_comment_min() -> float:
    try:
        return float(os.environ.get("JEV_AUTO_COMMENT_MIN", "0.85"))
    except ValueError:
        return 0.85


def hint_min() -> float:
    try:
        return float(os.environ.get("JEV_HINT_MIN", "0.55"))
    except ValueError:
        return 0.55


def route_action(probability: float, confidence: Optional[float] = None) -> str:
    """Map probability (and optional confidence) to auto_comment | hint_for_llm | ignore."""
    signal = confidence if confidence is not None else probability
    try:
        signal = float(signal)
    except (TypeError, ValueError):
        return "ignore"
    if signal >= auto_comment_min():
        return "auto_comment"
    if signal >= hint_min():
        return "hint_for_llm"
    return "ignore"


def guess_language(path: str) -> Optional[str]:
    ext = os.path.splitext(path or "")[1].lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".php": "php",
        ".cs": "csharp",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".sh": "shell",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".json": "json",
        ".md": "markdown",
        ".sql": "sql",
        ".tf": "terraform",
    }.get(ext)


def first_added_line(patch: Optional[str]) -> Optional[int]:
    if not patch:
        return None
    m = _HUNK_RE.search(patch)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def build_state(file_patch: dict) -> dict:
    path = file_patch.get("path") or file_patch.get("filename") or ""
    language = file_patch.get("language") or guess_language(path)
    patch = file_patch.get("patch") or ""
    state: dict[str, Any] = {"path": path, "patch": patch}
    if language:
        state["language"] = language
    return state


def build_questions() -> dict:
    """Parallel Noul + Score questions for every rule (one System One call)."""
    from typesafe_sdk import Noul, Score

    # NoulCriteria is a TypedDict — pass a plain dict (true/false descriptions).
    noul_criteria = {
        "true": "Yes — the patch clearly exhibits this risk.",
        "false": "No — the patch does not exhibit this risk.",
    }

    questions: dict[str, Any] = {}
    for rule_id, spec in RULE_SPECS.items():
        questions[rule_id] = Noul(instructions=spec["noul"], criteria=noul_criteria)
        questions[f"{rule_id}__severity"] = Score(
            instructions=spec["score"],
            criteria=list(SCORE_LEVELS),
        )
    return questions


def _attr(obj: Any, *names: str, default=None):
    for name in names:
        if obj is None:
            break
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def findings_from_response(
    response: Any,
    file_path: str,
    patch: Optional[str] = None,
) -> list[dict]:
    """Turn a System One response into Kenny finding dicts for one file."""
    nouls = _attr(response, "nouls", default={}) or {}
    scores = _attr(response, "scores", default={}) or {}
    start_line = first_added_line(patch)
    findings: list[dict] = []

    for rule_id, spec in RULE_SPECS.items():
        noul_ans = nouls.get(rule_id) if hasattr(nouls, "get") else _attr(nouls, rule_id)
        score_ans = (
            scores.get(f"{rule_id}__severity")
            if hasattr(scores, "get")
            else _attr(scores, f"{rule_id}__severity")
        )

        probability = _as_float(_attr(noul_ans, "noul", default=noul_ans))
        if probability is None:
            continue

        score_val = _as_float(_attr(score_ans, "score", default=None))
        # Route on Noul probability; Score supplies severity (+ optional confidence metadata).
        confidence = _as_float(_attr(score_ans, "confidence", default=None))
        action = route_action(probability)
        if action == "ignore":
            continue

        if score_val is not None:
            severity = _SEVERITY_FROM_SCORE.get(int(round(min(max(score_val, 0), 4))), spec["severity"])
        else:
            severity = spec["severity"]

        content_bits = [f"Jev rule `{rule_id}` fired with P(yes)={probability:.3f}."]
        if score_val is not None:
            content_bits.append(f"Severity score={score_val:.2f}/4.")
        if confidence is not None:
            content_bits.append(f"Score confidence={confidence:.3f}.")
        content_bits.append(
            "This is a System One triage signal — the LLM review may elaborate."
        )

        finding = {
            "rule_id": rule_id,
            "file": file_path,
            "start_line": start_line,
            "end_line": start_line,
            "header": spec["header"],
            "content": " ".join(content_bits),
            "severity": severity,
            "probability": probability,
            "action": action,
        }
        if confidence is not None:
            finding["confidence"] = confidence
        findings.append(finding)

    return findings


async def run_jev_checks(
    file_patches: Iterable[dict],
    *,
    model: Optional[str] = None,
    batch_size: int = 1,
) -> list[dict]:
    """Run System One per file (or small batches) and return routed findings."""
    patches = [p for p in file_patches if (p.get("patch") or "").strip()]
    if not patches:
        return []

    used_model = model or typesafe_model()
    questions = build_questions()
    all_findings: list[dict] = []

    # Per-file by default (batch_size=1). Larger batches concatenate state.
    for i in range(0, len(patches), max(1, batch_size)):
        chunk = patches[i : i + max(1, batch_size)]
        if len(chunk) == 1:
            state = build_state(chunk[0])
            path = state["path"]
            patch = state.get("patch")
        else:
            state = {
                "files": [build_state(p) for p in chunk],
            }
            path = ",".join(
                (p.get("path") or p.get("filename") or "") for p in chunk
            )
            patch = None

        response = await system_one(state=state, questions=questions, model=used_model)
        if len(chunk) == 1:
            all_findings.extend(
                findings_from_response(response, path, patch=patch)
            )
        else:
            # Batched: attribute findings to each path lightly (same signals).
            for p in chunk:
                p_path = p.get("path") or p.get("filename") or path
                all_findings.extend(
                    findings_from_response(response, p_path, patch=p.get("patch"))
                )

    return all_findings


def partition_findings(findings: list[dict]) -> dict[str, list[dict]]:
    auto_commented = [f for f in findings if f.get("action") == "auto_comment"]
    hints = [f for f in findings if f.get("action") == "hint_for_llm"]
    ignored = [f for f in findings if f.get("action") == "ignore"]
    return {
        "auto_commented": auto_commented,
        "hints": hints,
        "ignored": ignored,
        "all": findings,
    }


def format_hints_for_llm(hints: list[dict]) -> str:
    """Short structured block injected into the LLM review prompt."""
    if not hints:
        return ""
    lines = [
        "# KENNY Jev pre-check hints (TypeSafe System One)",
        "The following mid-confidence findings were produced by Jev before this LLM review.",
        "Use them as triage context; you still own explain/improve prose. Do not ignore high-severity items.",
        "",
    ]
    for h in hints:
        loc = h.get("file") or ""
        if h.get("start_line"):
            loc += f":{h['start_line']}"
        lines.append(
            f"- [{h.get('severity', 'medium')}] {h.get('rule_id')} @ {loc} "
            f"(p={h.get('probability')}) — {h.get('header')}: {h.get('content')}"
        )
    return "\n".join(lines)
