"""Adapter for Azure OpenAI Service.

Azure uses the same request/response format as OpenAI but differs in
authentication (``api-key`` header), URL layout (per-deployment paths) and
requires an ``api-version`` query parameter. The ``openai`` SDK's
``AzureOpenAI`` client handles those differences; ``LLM_MODEL`` must be set to
the *deployment name*.
"""

from __future__ import annotations

from openai import AzureOpenAI

from agent.providers.openai_compatible import OpenAICompatibleProvider


class AzureOpenAIProvider(OpenAICompatibleProvider):
    name = "azure"

    def _create_client(self):
        cfg = self.config
        return AzureOpenAI(
            api_key=cfg.api_key,
            azure_endpoint=cfg.base_url,
            api_version=cfg.azure_api_version,
            timeout=cfg.timeout,
            default_headers=dict(cfg.extra_headers) or None,
            max_retries=0,
        )
