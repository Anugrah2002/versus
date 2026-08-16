"""
Google Gemini 2.0/1.5 Flash Provider (Tertiary AI Fallback).
1,500 free requests/day with structured JSON response.
Includes Circuit Breaker for instant skipping on HTTP 429.
"""

import json
from typing import Optional, Dict, Any

from config.settings import settings
from src.synthesis.prompt_templates import SYSTEM_PROMPT_DEBATE, SYSTEM_PROMPT_SINGLE, build_synthesis_prompt
from src.storage.models import StoryCluster, ClusterClassification
from src.utils.logger import logger


class GeminiAIProvider:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model = settings.GEMINI_MODEL
        self._is_rate_limited = False

    @property
    def is_configured(self) -> bool:
        if self._is_rate_limited:
            return False
        return bool(self.api_key)

    def synthesize_cluster(self, cluster: StoryCluster) -> Optional[Dict[str, Any]]:
        if not self.is_configured:
            return None

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}

        is_debate = cluster.classification in (
            ClusterClassification.NEW_DEBATE,
            ClusterClassification.UPGRADE_STORY
        )
        system_prompt = SYSTEM_PROMPT_DEBATE if is_debate else SYSTEM_PROMPT_SINGLE
        user_prompt = build_synthesis_prompt(cluster.articles, cluster.category, cluster.classification)

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"System Instructions:\n{system_prompt}\n\nTask:\n{user_prompt}"}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "maxOutputTokens": 1024
            }
        }

        try:
            import requests
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.status_code in (429, 402, 403):
                self._is_rate_limited = True
                logger.warning(
                    f"⚡ [CIRCUIT BREAKER TRIPPED] Gemini Flash API rate-limited (HTTP {response.status_code}). "
                    f"Skipping Gemini for subsequent stories in this batch."
                )
                return None

            if response.status_code != 200:
                logger.warning(f"Gemini API returned HTTP {response.status_code}: {response.text[:150]}")
                return None

            data = response.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(content)
        except Exception as e:
            logger.warning(f"Gemini API call failed: {e}")
            return None
