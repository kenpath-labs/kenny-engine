# KENNY
"""Publish high-confidence Jev findings as PR / commit comments.

Reuses the patterns in publish.py with marker ``<!-- kenny-jev -->``.
"""

from __future__ import annotations

from typing import Optional

JEV_MARKER = "<!-- kenny-jev -->"

SEVERITY_BADGE = {
    "critical": "🔴 **Critical**",
    "high": "🟠 **High**",
    "medium": "🟡 **Medium**",
    "low": "🔵 **Low**",
}


def _log():
    from pr_agent.log import get_logger
    return get_logger()


def jev_summary_comment(findings: list[dict]) -> str:
    lines = [JEV_MARKER, "## Kenny Jev Checks (System One) ⚡", ""]
    if not findings:
        lines.append("No high-confidence Jev findings.")
        return "\n".join(lines)

    lines.append(
        f"**{len(findings)} auto-comment finding{'s' if len(findings) != 1 else ''}** "
        "from TypeSafe Jev (pre-LLM triage)."
    )
    lines.append("")
    for f in findings:
        badge = SEVERITY_BADGE.get(str(f.get("severity", "medium")).lower(), "")
        where = f.get("file", "")
        if f.get("start_line"):
            where += f":{f['start_line']}"
        p = f.get("probability")
        p_str = f"{float(p):.2f}" if p is not None else "?"
        lines += [
            f"<details><summary>{badge} — {f.get('header', f.get('rule_id', 'Finding'))} "
            f"(<code>{where}</code>, p={p_str})</summary>",
            "",
            f.get("content", ""),
            "",
            f"<sub>rule=`{f.get('rule_id', '')}` · action=`{f.get('action', '')}`</sub>",
            "",
            "</details>",
            "",
        ]
    return "\n".join(lines)


def publish_jev_pr_findings(
    git_provider,
    findings: list[dict],
    *,
    inline: bool = True,
) -> dict:
    """Post summary (+ optional inline) for auto_comment findings on a PR."""
    auto = [f for f in findings if f.get("action") == "auto_comment"]
    posted_inline = 0

    if inline and auto:
        comments = []
        for f in auto:
            relevant_file = (f.get("file") or "").strip()
            line = f.get("start_line")
            if not relevant_file or not line:
                continue
            severity = str(f.get("severity", "medium")).lower()
            body = (
                f"{JEV_MARKER}\n"
                f"{SEVERITY_BADGE.get(severity, '')} — **{f.get('header', 'Jev finding')}**\n\n"
                f"{f.get('content', '')}\n\n"
                f"<sub>— Kenny Jev (`{f.get('rule_id', '')}`)</sub>"
            )
            try:
                comments.append(
                    git_provider.create_inline_comment(
                        body, relevant_file, "", absolute_position=int(line)
                    )
                )
            except Exception as e:
                _log().warning(
                    f"Kenny Jev could not place inline comment on {relevant_file}:{line}: {e}"
                )
        comments = [c for c in comments if c]
        if comments:
            try:
                git_provider.publish_inline_comments(comments)
                posted_inline = len(comments)
            except Exception as e:
                _log().warning(f"Kenny Jev inline comments failed: {e}")

    body = jev_summary_comment(auto)
    try:
        git_provider.publish_persistent_comment(
            body,
            initial_header="## Kenny Jev Checks (System One) ⚡",
            update_header=True,
            name="kenny_jev",
            final_update_message=False,
        )
        summary_posted = True
    except Exception:
        try:
            git_provider.publish_comment(body)
            summary_posted = True
        except Exception as e:
            _log().error(f"Kenny Jev could not publish summary: {e}")
            summary_posted = False

    return {"summary_posted": summary_posted, "inline_posted": posted_inline, "count": len(auto)}


def publish_jev_commit_findings(
    github_client,
    owner: str,
    repo: str,
    commit_sha: str,
    findings: list[dict],
) -> dict:
    """Post a commit comment for high-confidence findings when possible."""
    auto = [f for f in findings if f.get("action") == "auto_comment"]
    if not auto:
        return {"commit_comment_posted": False, "count": 0}

    body = jev_summary_comment(auto)
    try:
        repo_obj = github_client.get_repo(f"{owner}/{repo}")
        commit = repo_obj.get_commit(commit_sha)
        commit.create_comment(body)
        return {"commit_comment_posted": True, "count": len(auto)}
    except Exception as e:
        _log().warning(f"Kenny Jev commit comment failed for {owner}/{repo}@{commit_sha}: {e}")
        return {"commit_comment_posted": False, "count": len(auto), "error": str(e)}
