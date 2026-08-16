"""
Cloudflare Workers AI Provider for Dual-Perspective Stance Synthesis.
Calls Cloudflare Workers AI REST API directly with zero SDK dependencies.
Includes Circuit Breaker to instantly skip Cloudflare for the rest of the run upon HTTP 429 / Quota Exhaustion.
"""

import json
import re
from typing import Optional, Dict, Any, Union

from config.settings import settings
from src.synthesis.prompt_templates import SYSTEM_PROMPT_DEBATE, SYSTEM_PROMPT_SINGLE, build_synthesis_prompt
from src.storage.models import StoryCluster, ClusterClassification
from src.utils.logger import logger


class CloudflareAIProvider:
    def __init__(self):
        self.account_id = settings.CLOUDFLARE_ACCOUNT_ID
        self.api_token = settings.CLOUDFLARE_API_TOKEN
        self.model = settings.CLOUDFLARE_AI_MODEL
        self._is_rate_limited = False
        self._rate_limit_reason = ""

    @property
    def is_configured(self) -> bool:
        if self._is_rate_limited:
            return False
        return bool(self.account_id and self.api_token)

    def _extract_json_from_response(self, raw_input: Union[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if isinstance(raw_input, dict):
            return raw_input

        if not isinstance(raw_input, str):
            return None

        clean = raw_input.strip()
        clean = re.sub(r"^```(?:json)?", "", clean, flags=re.MULTILINE)
        clean = re.sub(r"```$", "", clean, flags=re.MULTILINE).strip()

        try:
            return json.loads(clean)
        except Exception:
            match = re.search(r"(\{.*\})", clean, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except Exception:
                    pass
        return None

    def synthesize_cluster(self, cluster: StoryCluster) -> Optional[Dict[str, Any]]:
        if not self.is_configured:
            return None

        url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{self.model}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

        is_debate = cluster.classification in (
            ClusterClassification.NEW_DEBATE,
            ClusterClassification.UPGRADE_STORY
        )
        system_prompt = SYSTEM_PROMPT_DEBATE if is_debate else SYSTEM_PROMPT_SINGLE
        user_prompt = build_synthesis_prompt(cluster.articles, cluster.category, cluster.classification)

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 1024
        }

        try:
            import requests
            response = requests.post(url, headers=headers, json=payload, timeout=25)

            # Circuit Breaker: If rate-limited (429) or quota exhausted (402/403), trip breaker immediately
            if response.status_code in (429, 402, 403) or "neurons" in response.text.lower():
                self._is_rate_limited = True
                self._rate_limit_reason = f"HTTP {response.status_code}: {response.text[:120]}"
                logger.warning(
                    f"⚡ [CIRCUIT BREAKER TRIPPED] Cloudflare AI daily neuron quota exhausted or rate-limited. "
                    f"Skipping Cloudflare for all subsequent stories in this batch. Reason: {self._rate_limit_reason}"
                )
                return None

            if response.status_code != 200:
                logger.warning(f"Cloudflare AI returned HTTP {response.status_code}: {response.text[:150]}")
                return None

            res_data = response.json()
            result_obj = res_data.get("result", {})
            if isinstance(result_obj, dict):
                result_data = result_obj.get("response", result_obj)
            else:
                result_data = result_obj

            if not result_data:
                return None

            parsed_json = self._extract_json_from_response(result_data)
            if parsed_json and isinstance(parsed_json, dict) and "title" in parsed_json and "perspectives" in parsed_json:
                return parsed_json

            return None
        except Exception as e:
            logger.warning(f"Cloudflare Workers AI call failed: {e}")
            return None
