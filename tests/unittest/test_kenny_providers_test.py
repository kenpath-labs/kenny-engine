# KENNY
from unittest.mock import AsyncMock, patch

import pytest

from pr_agent.servers.kenny_api import ProviderTestRequest, providers_test


class TestKennyProvidersTest:
    """The dashboard's provider "Test" button (POST /kenny/v1/providers/test)."""

    @pytest.mark.asyncio
    async def test_probe_sends_no_output_cap(self):
        """Regression: the probe sent max_tokens=10, which newer OpenAI models reject.

        LiteLLM only renames max_tokens to max_completion_tokens for model ids it already
        knows, so a model newer than the pinned LiteLLM failed the test with
        "Unsupported parameter: 'max_tokens' is not supported with this model".
        """
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_completion:
            result = await providers_test(ProviderTestRequest(
                litellm_model="openai/gpt-6.1-sol",
                api_base="https://api.openai.com/v1",
                api_key="sk-test",
            ))

        assert result["ok"] is True
        assert result["error"] is None
        call_kwargs = mock_completion.call_args[1]
        assert "max_tokens" not in call_kwargs
        assert "max_completion_tokens" not in call_kwargs
        assert call_kwargs["model"] == "openai/gpt-6.1-sol"
        assert call_kwargs["api_base"] == "https://api.openai.com/v1"
        assert call_kwargs["api_key"] == "sk-test"

    @pytest.mark.asyncio
    async def test_probe_reports_the_provider_error(self):
        """A failing provider comes back as ok=False with the provider's own message."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_completion:
            mock_completion.side_effect = RuntimeError("Incorrect API key provided")
            result = await providers_test(ProviderTestRequest(litellm_model="openai/gpt-6.1-sol"))

        assert result["ok"] is False
        assert "Incorrect API key provided" in result["error"]
