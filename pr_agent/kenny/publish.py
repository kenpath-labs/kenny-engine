# KENNY
"""Publish a Kenny review onto the pull request itself.

The stock reviewer posts a single summary table; findings carry file and line
numbers, so post them as inline comments too — that's what makes a review
actionable in the GitHub UI.
"""

from typing import Optional

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
SEVERITY_BADGE = {
    "critical": "🔴 **Critical**",
    "high": "🟠 **High**",
    "medium": "🟡 **Medium**",
    "low": "🔵 **Low**",
}

KENNY_MARKER = "<!-- kenny-review -->"


def _log():
    from pr_agent.log import get_logger
    return get_logger()


def _meets_threshold(severity: str, threshold: str) -> bool:
    return SEVERITY_ORDER.get(severity, 1) >= SEVERITY_ORDER.get(threshold, 1)


def summary_comment(findings: list[dict], effort=None, security: Optional[str] = None) -> str:
    """The overview Kenny leaves on the conversation tab."""
    lines = [KENNY_MARKER, "## Kenny Reviewer Guide 🔍", ""]

    if effort:
        try:
            n = int(str(effort).split(",")[0].strip())
            lines.append(f"**Estimated review effort:** {n}/5 " + "🔵" * n + "⚪" * (5 - n))
            lines.append("")
        except (TypeError, ValueError):
            pass

    if security and security.strip().lower() not in ("no", "none", "n/a", ""):
        lines += ["> [!WARNING]", f"> **Security concerns** — {security.strip()}", ""]

    if not findings:
        lines.append("No issues worth flagging in this change. ✅")
        return "\n".join(lines)

    by_sev: dict[str, int] = {}
    for f in findings:
        by_sev[f.get("severity", "medium")] = by_sev.get(f.get("severity", "medium"), 0) + 1
    tally = " · ".join(
        f"{SEVERITY_BADGE.get(s, s)} {n}"
        for s, n in sorted(by_sev.items(), key=lambda kv: -SEVERITY_ORDER.get(kv[0], 1))
    )
    lines += [f"**{len(findings)} finding{'s' if len(findings) != 1 else ''}** — {tally}", ""]

    for f in findings:
        badge = SEVERITY_BADGE.get(f.get("severity", "medium"), "")
        where = f.get("file", "")
        if f.get("start_line"):
            where += f":{f['start_line']}"
        lines += [
            f"<details><summary>{badge} — {f.get('header', 'Finding')} "
            f"(<code>{where}</code>)</summary>",
            "",
            f.get("content", ""),
            "",
            "</details>",
            "",
        ]
    return "\n".join(lines)


def publish_review(git_provider, findings: list[dict], effort=None,
                   security: Optional[str] = None,
                   inline: bool = True, threshold: str = "medium") -> dict:
    """Post the summary, plus one inline comment per finding above `threshold`.

    Returns what was actually published so the caller can report it.
    """
    posted_inline = 0

    if inline and findings:
        comments = []
        for f in findings:
            severity = str(f.get("severity", "medium")).lower()
            if not _meets_threshold(severity, threshold):
                continue
            relevant_file = (f.get("file") or "").strip()
            line = f.get("start_line")
            if not relevant_file or not line:
                continue
            body = (
                f"{SEVERITY_BADGE.get(severity, '')} — **{f.get('header', 'Finding')}**\n\n"
                f"{f.get('content', '')}\n\n"
                f"<sub>— Kenny</sub>"
            )
            try:
                comments.append(
                    git_provider.create_inline_comment(body, relevant_file, "", absolute_position=int(line))
                )
            except Exception as e:
                _log().warning(f"Kenny could not place an inline comment on {relevant_file}:{line}: {e}")
        comments = [c for c in comments if c]
        if comments:
            try:
                git_provider.publish_inline_comments(comments)
                posted_inline = len(comments)
            except Exception as e:
                _log().warning(f"Kenny inline comments failed, falling back to summary only: {e}")

    body = summary_comment(findings, effort=effort, security=security)
    try:
        # Replace Kenny's previous verdict rather than stacking a new one per run.
        git_provider.publish_persistent_comment(
            body,
            initial_header="## Kenny Reviewer Guide 🔍",
            update_header=True,
            name="kenny_review",
            final_update_message=False,
        )
    except Exception:
        git_provider.publish_comment(body)

    return {"summary_posted": True, "inline_posted": posted_inline}
