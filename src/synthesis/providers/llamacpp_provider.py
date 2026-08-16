"""
Local Llama.cpp CPU Inference Provider (Google Gemma / Llama / Qwen GGUF).
Runs 100% offline on standard 2-vCPU / 7GB RAM GitHub Actions runners with zero cloud API keys.
Supports Gemma 2/4-bit and 4B-class instruction-tuned models with automatic chat template adaptation.
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

# Default: Google Gemma 4-Bit Instruction-Tuned (Q4_K_M)
DEFAULT_MODEL_FILENAME = os.getenv(
    "LOCAL_GGUF_MODEL_FILENAME",
    "gemma-2-2b-it-Q4_K_M.gguf"
)
DEFAULT_MODEL_URL = os.getenv(
    "LOCAL_GGUF_MODEL_URL",
    "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q4_K_M.gguf"
)


class LlamaCppProvider:
    def __init__(self):
        self._llm = None
        self._is_initialized = False
        self.model_filename = DEFAULT_MODEL_FILENAME
        self.model_url = DEFAULT_MODEL_URL
        self.model_path = MODEL_DIR / self.model_filename

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
            logger.info(f"Downloading Google Gemma GGUF model '{self.model_filename}' from {self.model_url}...")
            urllib.request.urlretrieve(self.model_url, str(self.model_path))
            logger.info("Gemma model download complete.")
            return True
        except Exception as e:
            logger.warning(f"Could not download Gemma GGUF model: {e}")
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
            logger.info(f"Loading Gemma model '{self.model_filename}' into memory on 2 CPU threads...")
            self._llm = Llama(
                model_path=str(self.model_path),
                n_ctx=3584,
                n_threads=2,
                n_batch=512,
                verbose=False
            )
            self._is_initialized = True
            logger.info("Local Gemma llama.cpp model loaded successfully.")
            return True
        except Exception as e:
            logger.warning(f"Failed to load Gemma llama.cpp model: {e}")
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
            logger.info(f"Synthesizing cluster {cluster.cluster_id} via local Gemma CPU...")
            response = self._llm.create_chat_completion(
                messages=messages,
                temperature=0.25,
                max_tokens=1024,
                response_format={"type": "json_object"}
            )

            content = response["choices"][0]["message"]["content"].strip()
            
            # Extract JSON
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                return json.loads(match.group(0))
            return json.loads(content)
        except Exception as e:
            logger.warning(f"Gemma local synthesis failed: {e}")
            return None


llamacpp_provider = LlamaCppProvider()
