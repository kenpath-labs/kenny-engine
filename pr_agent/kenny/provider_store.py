# KENNY
"""Read-only access to the `providers` table managed by the kenny-review dashboard.

The engine never writes providers; the dashboard owns the schema (drizzle) and CRUD.
Keys are Fernet-encrypted at rest with KENNY_SECRET_KEY, and the engine is the only
decryptor. Everything degrades gracefully: no DATABASE_URL, no table, or an empty
table simply means "no provider override" and the env-based config stays in effect.
"""

import os
import time
from dataclasses import dataclass
from typing import Optional

from pr_agent.log import get_logger

_CACHE_TTL_SECONDS = 30


@dataclass
class Provider:
    id: str
    name: str
    litellm_model: str
    api_base: Optional[str]
    api_key: Optional[str]  # decrypted; None when the endpoint is unauthenticated
    max_tokens: Optional[int]
    fallback_order: Optional[int]
    is_active: bool


_cache: dict = {"at": 0.0, "providers": None}


def _fernet():
    secret = os.environ.get("KENNY_SECRET_KEY")
    if not secret:
        return None
    from cryptography.fernet import Fernet
    return Fernet(secret.encode())


def _decrypt(enc: Optional[str]) -> Optional[str]:
    if not enc:
        return None
    f = _fernet()
    if f is None:
        get_logger().warning("KENNY_SECRET_KEY unset; cannot decrypt provider key")
        return None
    try:
        return f.decrypt(enc.encode()).decode()
    except Exception:
        get_logger().error("Failed to decrypt provider api key")
        return None


def _load_providers() -> list[Provider]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return []
    try:
        import psycopg
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            rows = conn.execute(
                "SELECT id::text, name, litellm_model, api_base, api_key_enc,"
                "       max_tokens, fallback_order, is_active"
                "  FROM providers ORDER BY fallback_order NULLS LAST, created_at"
            ).fetchall()
    except Exception as e:
        # Missing table (pre-migration) or transient DB issue: behave as "no providers"
        get_logger().warning(f"Kenny provider store unavailable: {e}")
        return []
    return [
        Provider(
            id=r[0], name=r[1], litellm_model=r[2], api_base=r[3],
            api_key=_decrypt(r[4]), max_tokens=r[5], fallback_order=r[6],
            is_active=bool(r[7]),
        )
        for r in rows
    ]


def get_providers(force_refresh: bool = False) -> list[Provider]:
    now = time.monotonic()
    if force_refresh or _cache["providers"] is None or now - _cache["at"] > _CACHE_TTL_SECONDS:
        _cache["providers"] = _load_providers()
        _cache["at"] = now
    return _cache["providers"]


def get_provider(provider_id: str) -> Optional[Provider]:
    return next((p for p in get_providers() if p.id == provider_id), None)


def get_active_provider() -> Optional[Provider]:
    return next((p for p in get_providers() if p.is_active), None)


def apply_provider_to_settings(settings, provider: Provider) -> None:
    """Mutate a request-scoped settings object to route LiteLLM at this provider.

    Must only be called on a per-request deepcopy (see kenny.settings_context),
    never on global_settings.
    """
    settings.set("CONFIG.MODEL", provider.litellm_model)
    settings.set("CONFIG.FALLBACK_MODELS", [provider.litellm_model])
    fallbacks = sorted(
        (p for p in get_providers() if not p.is_active and p.fallback_order is not None),
        key=lambda p: p.fallback_order,
    )
    if provider.is_active and fallbacks:
        settings.set("CONFIG.FALLBACK_MODELS",
                     [provider.litellm_model] + [p.litellm_model for p in fallbacks])
    if provider.max_tokens:
        settings.set("CONFIG.CUSTOM_MODEL_MAX_TOKENS", provider.max_tokens)
    if provider.api_base:
        settings.set("OPENAI.API_BASE", provider.api_base)
    if provider.api_key:
        settings.set("OPENAI.KEY", provider.api_key)
