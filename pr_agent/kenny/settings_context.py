# KENNY
"""Request-scoped settings for the Kenny JSON API.

Mirrors the pattern in servers/github_app.py: each request gets a deepcopy of
global_settings stored in starlette_context, so per-request mutations (model,
api_base, publish_output) never leak across concurrent requests. Requires the
app to be wrapped in RawContextMiddleware (kenny_server does this).
"""

import copy
from typing import Optional

from starlette_context import context

from pr_agent.config_loader import global_settings
from pr_agent.kenny.provider_store import apply_provider_to_settings, get_active_provider, get_provider


class UnknownProviderError(Exception):
    pass


def kenny_request_settings(provider_id: Optional[str] = None):
    """Install a request-scoped settings copy configured for API (non-publishing) use.

    Provider resolution: explicit provider_id -> active provider -> env config as-is.
    Returns the settings object now active for this request via get_settings().
    """
    if not context.exists():
        raise RuntimeError("starlette_context missing; kenny_api must run under RawContextMiddleware")
    settings = copy.deepcopy(global_settings)
    context["settings"] = settings
    context["git_provider"] = {}

    # Under GitHub App auth the provider needs an installation id, which only
    # webhook payloads carry. Dashboard-triggered calls resolve it themselves.
    if settings.get("GITHUB.DEPLOYMENT_TYPE", "user") == "app":
        from pr_agent.kenny.github_app_auth import get_installation_id
        installation_id = get_installation_id()
        if installation_id:
            context["installation_id"] = installation_id

    provider = None
    if provider_id:
        provider = get_provider(provider_id)
        if provider is None:
            raise UnknownProviderError(f"Unknown provider_id: {provider_id}")
    else:
        provider = get_active_provider()
    if provider is not None:
        apply_provider_to_settings(settings, provider)

    settings.set("CONFIG.PUBLISH_OUTPUT", False)
    settings.set("CONFIG.PUBLISH_OUTPUT_PROGRESS", False)
    return settings
