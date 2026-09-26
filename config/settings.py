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

    # Database Configuration (MySQL / SQLite)
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "toor"
    DB_NAME: str = "ai_news"
    DATABASE_URL: str = "mysql+pymysql://root:toor@localhost:3306/ai_news?charset=utf8mb4"
    SQL_ECHO: bool = False

    # Web Server Configuration
    SERVER_HOST: str = "127.0.0.1"
    SERVER_PORT: int = 8080

    # Mail Server (SMTP) Defaults — sandbox Mailtrap credentials
    MAIL_SERVER: str = "sandbox.smtp.mailtrap.io"
    MAIL_PORT: int = 2525
    MAIL_USERNAME: str = "6056bdc6c17f23"
    MAIL_PASSWORD: str = "4e1119bb236ac7"
    MAIL_USE_TLS: bool = True
    MAIL_USE_SSL: bool = False
    MAIL_DEFAULT_SENDER: str = "no-reply@daily-ai-alo.com"

    # SSLCommerz Payment Gateway (Sandbox) Defaults
    SSLCOMMERZ_STORE_ID: str = "arobw6a3cf7767fa7c"
    SSLCOMMERZ_STORE_PASSWORD: str = "arobw6a3cf7767fa7c@ssl"
    SSLCOMMERZ_SANDBOX_URL: str = "https://sandbox.sslcommerz.com"
    SSLCOMMERZ_LIVE_URL: str = "https://securepay.sslcommerz.com"
    SSLCOMMERZ_IS_LIVE: bool = False

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

    # Mail Server Configuration (Default: Mailtrap Sandbox)
    MAIL_SERVER: str = "sandbox.smtp.mailtrap.io"
    MAIL_PORT: int = 2525
    MAIL_USERNAME: str = "6056bdc6c17f23"
    MAIL_PASSWORD: str = "4e1119bb236ac7"
    MAIL_USE_TLS: bool = True
    MAIL_USE_SSL: bool = False
    MAIL_DEFAULT_SENDER: str = "noreply@webcreoling.ai"
    MAIL_SENDER_NAME: str = "WebCreoling AI Newsroom"

    # SMS Gateway Configuration
    SMS_PROVIDER: str = "SANDBOX"  # SANDBOX, SSL_WIRELESS, GREENWEB, BULKSMS_BD, TWILIO
    SMS_API_KEY: str = "sandbox_sms_api_key_bangla_news"
    SMS_SENDER_ID: str = "WEBCREOLING"
    SMS_API_URL: str = "https://api.sms-gateway.mock/v1/send"

    # Payment Gateway Configuration
    PAYMENT_GATEWAY_DEFAULT: str = "BKASH"  # BKASH, NAGAD, ROCKET, SSLCOMMERZ, STRIPE, SANDBOX
    BKASH_APP_KEY: str = "sandbox_bkash_app_key_88017"
    BKASH_APP_SECRET: str = "sandbox_bkash_secret_secure_9901"
    BKASH_MERCHANT_NUMBER: str = "01700000000"
    NAGAD_MERCHANT_ID: str = "sandbox_nagad_merchant_123"
    NAGAD_PUBLIC_KEY: str = "sandbox_nagad_pub_key"
    SSLCOMMERZ_STORE_ID: str = "webcreoling_sandbox_store"
    SSLCOMMERZ_STORE_PASS: str = "webcreoling_sandbox_pass@123"
    STRIPE_PUBLIC_KEY: str = "pk_test_sample_51O..."
    STRIPE_SECRET_KEY: str = "sk_test_sample_51O..."

    # Localization Default
    DEFAULT_LANGUAGE: str = "bn"  # 'bn' (Bangla) or 'en' (English)

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
