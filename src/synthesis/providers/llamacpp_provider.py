"""
Local Llama.cpp CPU Inference Provider (Llama-3.2-1B / Qwen2.5-1.5B GGUF).
Runs 100% offline on standard 2-vCPU / 7GB RAM GitHub Actions runners with zero cloud API keys.
"""

from typing import Optional, Dict, Any
import os
import json
import re
from pathlib import Path

from src.storage.models import StoryCluster
from src.synthesis.prompt_templates import (
    SYSTEM_PROMPT_DEBATE,
    SYSTEM_PROMPT_SINGLE,
    build_synthesis_prompt
)
from src.utils.logger import logger

MODEL_DIR = Path(".models")
MODEL_FILENAME = "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
MODEL_URL = "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf"


class LlamaCppProvider:
    def __init__(self):
        self._llm = None
        self._is_initialized = False
        self.model_path = MODEL_DIR / MODEL_FILENAME

    @property
    def is_available(self) -> bool:
        try:
            import llama_cpp
            return True
        except ImportError:
            return False

    def _ensure_model_downloaded(self) -> bool:
        if self.model_path.exists() and self.model_path.stat().st_size > 100_000_000:
            return True

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        try:
            import urllib.request
            logger.info(f"Downloading lightweight CPU model {MODEL_FILENAME} (~750MB)...")
            urllib.request.urlretrieve(MODEL_URL, str(self.model_path))
            logger.info("Model download complete.")
            return True
        except Exception as e:
            logger.warning(f"Could not download GGUF model: {e}")
            return False

    def _init_llm(self) -> bool:
        if self._is_initialized:
            return self._llm is not None

        if not self.is_available:
            self._is_initialized = True
            return False

        if not self._ensure_model_downloaded():
            self._is_initialized = True
            return False

        try:
            from llama_cpp import Llama
            logger.info(f"Loading {MODEL_FILENAME} into memory on 2 CPU threads...")
            self._llm = Llama(
                model_path=str(self.model_path),
                n_ctx=3072,
                n_threads=2,
                n_batch=512,
                verbose=False
            )
            self._is_initialized = True
            logger.info("Local llama.cpp model loaded successfully.")
            return True
        except Exception as e:
            logger.warning(f"Failed to load llama.cpp model: {e}")
            self._is_initialized = True
            self._llm = None
            return False

    def synthesize_cluster(self, cluster: StoryCluster) -> Optional[Dict[str, Any]]:
        if not self._init_llm() or self._llm is None:
            return None

        is_debate = cluster.classification.value in ("new_debate", "upgrade_story")
        system_prompt = SYSTEM_PROMPT_DEBATE if is_debate else SYSTEM_PROMPT_SINGLE
        user_prompt = build_synthesis_prompt(
            cluster.articles,
            cluster.category,
            cluster.classification
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            logger.info(f"Synthesizing cluster {cluster.cluster_id} via local llama.cpp CPU...")
            response = self._llm.create_chat_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
                response_format={"type": "json_object"}
            )

            content = response["choices"][0]["message"]["content"].strip()
            
            # Parse JSON
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                return json.loads(match.group(0))
            return json.loads(content)
        except Exception as e:
            logger.warning(f"llama.cpp local synthesis failed: {e}")
            return None


llamacpp_provider = LlamaCppProvider()
