"""
OpenAI client configuration and initialization.
Follows coding standards: use circuit breaker for external API calls.
"""

import logging
from typing import Optional
from openai import AsyncOpenAI

from config.settings import settings

logger = logging.getLogger(__name__)


class OpenAIClient:
    """OpenAI client wrapper with configuration and error handling."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize OpenAI client with configuration.

        Args:
            api_key: OpenAI API key, defaults to settings if not provided
        """
        self._api_key = api_key or settings.openai_api_key
        self._client: Optional[AsyncOpenAI] = None
        self._model = settings.get_openai_model()
        
        if not self._api_key:
            logger.error("OpenAI API key not configured")
            raise ValueError("OPENAI_API_KEY environment variable is required")

    @property
    def client(self) -> AsyncOpenAI:
        """
        Get or create OpenAI async client.

        Returns:
            Configured AsyncOpenAI client
        """
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                timeout=30.0,  # 30 second timeout
            )
            logger.info(
                "OpenAI client initialized", 
                extra={
                    "context": {
                        "service_context": "OpenAIClient.client:property",
                        "model": self._model,
                        "reasoning_level": settings.llm_reasoning_level,
                        "verbosity": settings.llm_verbosity
                    }
                }
            )
        return self._client

    @property 
    def model(self) -> str:
        """Get configured model name."""
        return self._model

    def get_model_config(self) -> dict:
        """
        Get model configuration for chat completion requests.

        Returns:
            Dictionary with model configuration parameters
        """
        config = {
            "model": self._model,
            "temperature": 0.1,  # Low temperature for consistent parsing
            "response_format": {"type": "json_object"}  # Structured JSON output
        }
        
        # Add reasoning configuration and token limits for o1/gpt-5 series models
        if "gpt-5" in self._model.lower() or "o1" in self._model.lower():
            config["reasoning_effort"] = settings.llm_reasoning_level
            config["max_completion_tokens"] = 1000  # Use new parameter for GPT-5
        else:
            config["max_tokens"] = 1000  # Use legacy parameter for older models
            
        return config

    async def close(self):
        """Clean up client resources."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("OpenAI client closed")


# Global client instance
openai_client = OpenAIClient()