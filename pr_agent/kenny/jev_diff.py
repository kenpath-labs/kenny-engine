# KENNY
"""Fetch structured file patches for Jev checks (PR diffs and commit SHAs)."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from pr_agent.kenny.jev_checks import guess_language


def parse_commit_url(commit_url: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse https://github.com/{owner}/{repo}/commit/{sha} → owner, repo, sha."""
    try:
        parts = [p for p in urlparse(commit_url).path.split("/") if p]
        idx = parts.index("commit")
        if idx >= 2 and idx + 1 < len(parts):
            return parts[idx - 2], parts[idx - 1], parts[idx + 1]
    except ValueError:
        pass
    return None, None, None


def file_patches_from_diff_files(diff_files) -> list[dict]:
    out = []
    for f in diff_files or []:
        path = getattr(f, "filename", None) or (f.get("filename") if isinstance(f, dict) else None)
        patch = getattr(f, "patch", None) if not isinstance(f, dict) else f.get("patch")
        language = getattr(f, "language", None) if not isinstance(f, dict) else f.get("language")
        if not path or not patch:
            continue
        out.append({
            "path": path,
            "language": language or guess_language(path),
            "patch": patch,
        })
    return out


def fetch_pr_file_patches(pr_url: str) -> tuple[list[dict], object]:
    from pr_agent.git_providers import get_git_provider_with_context
    git_provider = get_git_provider_with_context(pr_url)
    return file_patches_from_diff_files(git_provider.get_diff_files()), git_provider


def fetch_commit_file_patches(owner: str, repo: str, commit_sha: str) -> list[dict]:
    """Single-commit patches via PyGithub Commits API (not a full compare).

    Gap: uses ``repo.get_commit(sha).files[].patch`` only. For PR-wide context prefer pr_url.
    """
    from pr_agent.git_providers.github_provider import GithubProvider

    provider = GithubProvider()  # no PR URL — reuse auth / client setup
    repo_obj = provider.github_client.get_repo(f"{owner}/{repo}")
    commit = repo_obj.get_commit(commit_sha)
    out = []
    for f in commit.files or []:
        patch = getattr(f, "patch", None)
        path = getattr(f, "filename", None)
        if not path or not patch:
            continue
        out.append({
            "path": path,
            "language": guess_language(path),
            "patch": patch,
        })
    return out
