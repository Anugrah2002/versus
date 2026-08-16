"""
Groq High-Speed Llama-3.3-70B Provider (Secondary AI Fallback).
14,400 free requests/day with JSON object enforcement.
Includes Circuit Breaker for instant skipping on HTTP 429.
"""

import json
from typing import Optional, Dict, Any

from config.settings import settings
from src.synthesis.prompt_templates import SYSTEM_PROMPT_DEBATE, SYSTEM_PROMPT_SINGLE, build_synthesis_prompt
from src.storage.models import StoryCluster, ClusterClassification
from src.utils.logger import logger


class GroqAIProvider:
    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.model = settings.GROQ_MODEL
        self._is_rate_limited = True

    @property
    def is_configured(self) -> bool:
        if self._is_rate_limited:
            return False
        return bool(self.api_key and self.api_key.startswith("gsk_"))

    def synthesize_cluster(self, cluster: StoryCluster) -> Optional[Dict[str, Any]]:
        if not self.is_configured:
            return None

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        is_debate = cluster.classification in (
            ClusterClassification.NEW_DEBATE,
            ClusterClassification.UPGRADE_STORY
        )
        system_prompt = SYSTEM_PROMPT_DEBATE if is_debate else SYSTEM_PROMPT_SINGLE
        user_prompt = build_synthesis_prompt(cluster.articles, cluster.category, cluster.classification)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 1024
        }

        try:
            import requests
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.status_code in (429, 402, 403):
                self._is_rate_limited = True
                logger.warning(
                    f"⚡ [CIRCUIT BREAKER TRIPPED] Groq API rate-limited (HTTP {response.status_code}). "
                    f"Skipping Groq for subsequent stories in this batch."
                )
                return None

            if response.status_code != 200:
                logger.warning(f"Groq API returned HTTP {response.status_code}: {response.text[:150]}")
                return None

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as e:
            logger.warning(f"Groq API call failed: {e}")
            return None
