# KENNY
"""Resolve the GitHub App installation for dashboard-triggered API calls.

Webhook requests carry an installation_id in the payload, but calls that come
from the Kenny dashboard do not — GithubProvider refuses to build App auth
without one. This resolves the org's installation once and caches it.
"""

import os
from typing import Optional


def _log():
    from pr_agent.log import get_logger
    return get_logger()


_cache: dict = {"installation_id": None}


def get_installation_id() -> Optional[int]:
    """The App's installation id for the configured org/repo, or None if unavailable.

    An explicit KENNY_GITHUB_INSTALLATION_ID wins; otherwise it is looked up from
    the App credentials and cached for the process lifetime (installations change
    only when someone installs or uninstalls the App).
    """
    if _cache["installation_id"] is not None:
        return _cache["installation_id"]

    explicit = os.environ.get("KENNY_GITHUB_INSTALLATION_ID")
    if explicit:
        try:
            _cache["installation_id"] = int(explicit)
            return _cache["installation_id"]
        except ValueError:
            _log().warning(f"KENNY_GITHUB_INSTALLATION_ID is not a number: {explicit!r}")

    from pr_agent.config_loader import get_settings
    settings = get_settings()
    app_id = settings.get("GITHUB.APP_ID", None)
    private_key = settings.get("GITHUB.PRIVATE_KEY", None)
    if not app_id or not private_key:
        return None

    org = os.environ.get("KENNY_GITHUB_ORG", "kenpath-labs")
    try:
        from github import GithubIntegration
        integration = GithubIntegration(app_id, private_key)
        installation = integration.get_org_installation(org)
        _cache["installation_id"] = installation.id
        _log().info(f"Kenny resolved GitHub App installation {installation.id} for {org}")
        return _cache["installation_id"]
    except Exception as e:
        _log().warning(f"Could not resolve GitHub App installation for {org}: {e}")
        return None
