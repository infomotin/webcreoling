"""
Application Settings & Configuration Management.
Uses Pydantic v2 BaseSettings for type-safe environment variable parsing.
"""

from pathlib import Path
from typing import Optional, List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Project Information
    APP_NAME: str = "WebCreoling News Pipeline"
    VERSION: str = "0.1.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Base Paths
    BASE_DIR: Path = PROJECT_ROOT
    DATA_DIR: Path = PROJECT_ROOT / "data"
    DB_DIR: Path = DATA_DIR / "db"
    IMAGES_DIR: Path = DATA_DIR / "images"
    PROCESSED_DATA_DIR: Path = DATA_DIR / "processed"
    CHECKPOINTS_DIR: Path = DATA_DIR / "checkpoints"
    MODELS_DIR: Path = DATA_DIR / "checkpoints"
    LOGS_DIR: Path = PROJECT_ROOT / "logs"
    CONFIG_DIR: Path = PROJECT_ROOT / "config"

    # Database Configuration
    DATABASE_URL: str = f"sqlite:///{DB_DIR / 'news_pipeline.db'}"
    SQL_ECHO: bool = False

    # Scraper Configuration
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 WebCreolingNewsBot/1.0"
    )
    DEFAULT_SCRAPE_DELAY: float = 1.0
    SCRAPE_DELAY_JITTER: float = 0.5
    MAX_SCRAPE_RETRIES: int = 3
    SCRAPE_RETRY_BACKOFF: float = 2.0
    REQUEST_TIMEOUT: int = 20
    MAX_IMAGE_SIZE_MB: int = 15
    SELENIUM_HEADLESS: bool = True
    SELENIUM_TIMEOUT: int = 15

    # LLM & Training Configuration (CPU-Friendly Defaults)
    BASE_MODEL_NAME: str = "distilgpt2"  # Lightweight for low-resource CPU
    FALLBACK_MODEL_NAME: str = "HuggingFaceTB/SmolLM2-135M"
    MAX_SEQ_LENGTH: int = 512
    TRAIN_BATCH_SIZE: int = 2
    EVAL_BATCH_SIZE: int = 2
    GRADIENT_ACCUMULATION_STEPS: int = 4
    LEARNING_RATE: float = 5e-4
    NUM_TRAIN_EPOCHS: int = 3
    WARMUP_RATIO: float = 0.05
    WEIGHT_DECAY: float = 0.01
    USE_CPU_ONLY: bool = True
    NUM_CPU_THREADS: int = 4
    SEED: int = 42

    # LoRA / PEFT Parameters
    LORA_R: int = 8
    LORA_ALPHA: int = 16
    LORA_DROPOUT: float = 0.05
    LORA_TARGET_MODULES: List[str] = ["c_attn", "c_proj", "q_proj", "v_proj", "k_proj", "out_proj"]

    # Chat & RAG Configuration
    RAG_TOP_K: int = 3
    MAX_GENERATION_TOKENS: int = 256
    TEMPERATURE: float = 0.7
    TOP_P: float = 0.9

    def create_required_directories(self) -> None:
        """Create necessary directories if they do not exist."""
        for path in [
            self.DATA_DIR,
            self.DB_DIR,
            self.IMAGES_DIR,
            self.PROCESSED_DATA_DIR,
            self.CHECKPOINTS_DIR,
            self.LOGS_DIR,
        ]:
            path.mkdir(parents=True, exist_ok=True)


# Global singleton settings instance
settings = Settings()
settings.create_required_directories()
