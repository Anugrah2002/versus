"""
Settings and configuration loader for Versus Backend.
Reads configuration from environment variables, .env file, or GitHub Action secrets.
Works seamlessly with pydantic-settings when installed, with a built-in standard library fallback.
"""

import os
import json
import base64
from typing import Optional, Dict, Any
from pathlib import Path


def _load_dotenv_file(filepath: str = ".env"):
    """Lightweight .env file parser without third-party dependencies."""
    p = Path(filepath)
    if p.exists() and p.is_file():
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass


_load_dotenv_file(".env")


try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import Field

    class Settings(BaseSettings):
        CLOUDFLARE_ACCOUNT_ID: Optional[str] = Field(default=None)
        CLOUDFLARE_API_TOKEN: Optional[str] = Field(default=None)
        CLOUDFLARE_AI_MODEL: str = Field(default="@cf/meta/llama-3.1-8b-instruct-fp8-fast")

        GROQ_API_KEY: Optional[str] = Field(default=None)
        GROQ_MODEL: str = Field(default="llama-3.3-70b-versatile")

        GEMINI_API_KEY: Optional[str] = Field(default=None)
        GEMINI_MODEL: str = Field(default="gemini-2.0-flash")

        FIREBASE_SERVICE_ACCOUNT_PATH: Optional[str] = Field(default=None)
        FIREBASE_SERVICE_ACCOUNT_JSON: Optional[str] = Field(default=None)
        FIRESTORE_PROJECT_ID: Optional[str] = Field(default="versus-news")
        FIRESTORE_COLLECTION_ARTICLES: str = Field(default="articles")
        FIRESTORE_COLLECTION_SYSTEM: str = Field(default="_system")

        FEEDS_CONFIG_PATH: str = Field(default="config/feeds.yaml")
        CATEGORIES_CONFIG_PATH: str = Field(default="config/categories.json")
        MAX_FEEDS_CONCURRENT: int = Field(default=30)
        PER_DOMAIN_MAX_CONCURRENT: int = Field(default=2)
        PER_DOMAIN_MIN_DELAY_MS: int = Field(default=200)
        SCRAPE_TIMEOUT_SECONDS: int = Field(default=10)
        MIN_ARTICLE_WORD_COUNT: int = Field(default=120)
        SIMILARITY_DISTANCE_THRESHOLD: float = Field(default=0.38)
        ACTIVE_STORY_WINDOW_HOURS: int = Field(default=48)
        DATA_RETENTION_DAYS: int = Field(default=30)
        ENABLE_LOCAL_FALLBACK: bool = Field(default=True)
        DRY_RUN: bool = Field(default=False)

        EMBEDDING_MODEL_NAME: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")
        EMBEDDING_CACHE_DIR: str = Field(default=".state_cache/embeddings")
        LOCAL_STATE_CACHE_PATH: str = Field(default=".state_cache/pipeline_state.json")

        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore"
        )

        def get_firebase_credentials_dict(self) -> Optional[dict]:
            if self.FIREBASE_SERVICE_ACCOUNT_JSON:
                raw = self.FIREBASE_SERVICE_ACCOUNT_JSON.strip()
                try:
                    if not raw.startswith("{"):
                        decoded = base64.b64decode(raw).decode("utf-8")
                        return json.loads(decoded)
                    return json.loads(raw)
                except Exception:
                    pass

            if self.FIREBASE_SERVICE_ACCOUNT_PATH:
                p = Path(self.FIREBASE_SERVICE_ACCOUNT_PATH)
                if p.exists() and p.is_file():
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            return json.load(f)
                    except Exception:
                        pass
            return None

    settings = Settings()

except ImportError:
    # Zero-dependency Fallback for Environments Without Pydantic-Settings
    class FallbackSettings:
        def __init__(self):
            self.CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
            self.CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
            self.CLOUDFLARE_AI_MODEL = os.getenv("CLOUDFLARE_AI_MODEL", "@cf/meta/llama-3.1-8b-instruct-fp8-fast")

            self.GROQ_API_KEY = os.getenv("GROQ_API_KEY")
            self.GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

            self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
            self.GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

            self.FIREBASE_SERVICE_ACCOUNT_PATH = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
            self.FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
            self.FIRESTORE_PROJECT_ID = os.getenv("FIRESTORE_PROJECT_ID", "versus-news")
            self.FIRESTORE_COLLECTION_ARTICLES = os.getenv("FIRESTORE_COLLECTION_ARTICLES", "articles")
            self.FIRESTORE_COLLECTION_SYSTEM = os.getenv("FIRESTORE_COLLECTION_SYSTEM", "_system")

            self.FEEDS_CONFIG_PATH = os.getenv("FEEDS_CONFIG_PATH", "config/feeds.yaml")
            self.CATEGORIES_CONFIG_PATH = os.getenv("CATEGORIES_CONFIG_PATH", "config/categories.json")
            self.MAX_FEEDS_CONCURRENT = int(os.getenv("MAX_FEEDS_CONCURRENT", "30"))
            self.PER_DOMAIN_MAX_CONCURRENT = int(os.getenv("PER_DOMAIN_MAX_CONCURRENT", "2"))
            self.PER_DOMAIN_MIN_DELAY_MS = int(os.getenv("PER_DOMAIN_MIN_DELAY_MS", "200"))
            self.SCRAPE_TIMEOUT_SECONDS = int(os.getenv("SCRAPE_TIMEOUT_SECONDS", "10"))
            self.MIN_ARTICLE_WORD_COUNT = int(os.getenv("MIN_ARTICLE_WORD_COUNT", "120"))
            self.SIMILARITY_DISTANCE_THRESHOLD = float(os.getenv("SIMILARITY_DISTANCE_THRESHOLD", "0.38"))
            self.ACTIVE_STORY_WINDOW_HOURS = int(os.getenv("ACTIVE_STORY_WINDOW_HOURS", "48"))
            self.DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "30"))
            self.ENABLE_LOCAL_FALLBACK = os.getenv("ENABLE_LOCAL_FALLBACK", "true").lower() in ("1", "true", "yes")
            self.DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes")

            self.EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
            self.EMBEDDING_CACHE_DIR = os.getenv("EMBEDDING_CACHE_DIR", ".state_cache/embeddings")
            self.LOCAL_STATE_CACHE_PATH = os.getenv("LOCAL_STATE_CACHE_PATH", ".state_cache/pipeline_state.json")

        def get_firebase_credentials_dict(self) -> Optional[dict]:
            if self.FIREBASE_SERVICE_ACCOUNT_JSON:
                raw = self.FIREBASE_SERVICE_ACCOUNT_JSON.strip()
                try:
                    if not raw.startswith("{"):
                        decoded = base64.b64decode(raw).decode("utf-8")
                        return json.loads(decoded)
                    return json.loads(raw)
                except Exception:
                    pass

            if self.FIREBASE_SERVICE_ACCOUNT_PATH:
                p = Path(self.FIREBASE_SERVICE_ACCOUNT_PATH)
                if p.exists() and p.is_file():
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            return json.load(f)
                    except Exception:
                        pass
            return None

    settings = FallbackSettings()
