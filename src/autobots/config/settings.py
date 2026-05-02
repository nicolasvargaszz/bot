"""
Configuration settings for the Automation System.
Uses pydantic-settings for environment variable management.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # ===========================================
    # Application
    # ===========================================
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    log_level: str = "INFO"
    
    # ===========================================
    # Database
    # ===========================================
    database_url: PostgresDsn = Field(
        default="postgresql://automation:automation@localhost:5432/automation"
    )
    database_pool_size: int = 5
    database_max_overflow: int = 10
    
    # ===========================================
    # Redis
    # ===========================================
    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    
    # ===========================================
    # GitHub
    # ===========================================
    github_token: str = ""
    github_username: str = ""
    github_org: str = ""
    github_pages_domain: str = ""
    
    # ===========================================
    # AI Providers
    # ===========================================
    ai_provider: Literal["openai", "azure"] = "azure"
    
    # OpenAI
    openai_api_key: str = ""
    
    # Azure OpenAI
    azure_openai_endpoint: str = ""
    azure_openai_key: str = ""
    azure_openai_deployment: str = "gpt-4"
    azure_openai_api_version: str = "2024-02-01"
    
    # ===========================================
    # Email (Resend)
    # ===========================================
    resend_api_key: str = ""
    from_email: str = "contacto@example.com"
    from_name: str = "Tu Nombre"
    reply_to_email: str = ""
    
    # ===========================================
    # WhatsApp (Twilio)
    # ===========================================
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = ""
    my_whatsapp_number: str = ""
    
    # ===========================================
    # Google Maps / Scraping
    # ===========================================
    google_maps_api_key: str = ""
    outscraper_api_key: str = ""
    scrape_delay_seconds: float = 2.0
    max_results_per_query: int = 50
    headless_browser: bool = True
    
    # ===========================================
    # Tracking
    # ===========================================
    tracking_domain: str = ""
    tracking_secret_key: str = "change-this-secret"
    enable_tracking_pixel: bool = True
    
    # ===========================================
    # Deployment
    # ===========================================
    vercel_token: str = ""
    vercel_org_id: str = ""
    netlify_token: str = ""
    netlify_site_id: str = ""
    
    # ===========================================
    # Feature Flags
    # ===========================================
    enable_whatsapp_outreach: bool = False
    enable_ai_copy_generation: bool = True
    enable_screenshot_mockups: bool = True
    enable_email_tracking: bool = True
    
    # ===========================================
    # Rate Limits
    # ===========================================
    max_daily_discoveries: int = 500
    max_daily_generations: int = 100
    max_daily_outreach: int = 50
    max_follow_ups_per_business: int = 2
    
    # ===========================================
    # Business Logic
    # ===========================================
    min_score_for_outreach: int = 50
    min_reviews_for_qualification: int = 5
    follow_up_delay_days: int = 3
    archive_after_days: int = 30
    
    @property
    def is_production(self) -> bool:
        return self.environment == "production"
    
    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Export settings instance
settings = get_settings()
