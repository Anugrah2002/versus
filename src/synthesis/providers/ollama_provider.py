"""
Local Ollama Qwen AI Provider for Versus Dual-Perspective Synthesis.
100% Local, zero cloud dependencies, zero API costs.
Calls Ollama REST API (qwen2.5:1.5b, qwen2.5:3b, or qwen2.5:0.5b) directly.
"""

import json
import re
import urllib.request
from typing import Optional, Dict, Any, Union

from config.settings import settings
from src.synthesis.prompt_templates import SYSTEM_PROMPT_DEBATE, SYSTEM_PROMPT_SINGLE, build_synthesis_prompt
from src.storage.models import StoryCluster, ClusterClassification
from src.utils.logger import logger


class OllamaQwenProvider:
    def __init__(self, ollama_url: str = "http://localhost:11434", model_name: str = "qwen2.5:1.5b"):
        self.ollama_url = ollama_url
        self.model_name = model_name
        self._is_available: Optional[bool] = None

    @property
    def is_configured(self) -> bool:
        if self._is_available is False:
            return False
        try:
            req = urllib.request.Request(f"{self.ollama_url}/api/tags", headers={"User-Agent": "VersusEngine"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    self._is_available = True
                    return True
        except Exception:
            self._is_available = False
        return False

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

        is_debate = cluster.classification in (
            ClusterClassification.NEW_DEBATE,
            ClusterClassification.UPGRADE_STORY
        )
        system_prompt = SYSTEM_PROMPT_DEBATE if is_debate else SYSTEM_PROMPT_SINGLE
        user_prompt = build_synthesis_prompt(cluster.articles, cluster.category, cluster.classification)

        full_prompt = f"{system_prompt}\n\nUser Request:\n{user_prompt}"

        req_data = {
            "model": self.model_name,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 750
            }
        }

        try:
            logger.info(f"Synthesizing cluster {cluster.cluster_id} with Local Ollama ({self.model_name})...")
            req = urllib.request.Request(
                f"{self.ollama_url}/api/generate",
                data=json.dumps(req_data).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                text = res.get("response", "").strip()
                parsed = self._extract_json_from_response(text)
                if parsed and "perspectives" in parsed and len(parsed["perspectives"]) >= (2 if is_debate else 1):
                    return parsed
        except Exception as e:
            logger.debug(f"Ollama Qwen synthesis call failed: {e}")

        return None


ollama_qwen_provider = OllamaQwenProvider()
