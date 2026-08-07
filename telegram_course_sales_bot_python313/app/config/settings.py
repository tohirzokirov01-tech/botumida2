"""
Pydantic Settings Management
Reads from environment variables with dynamic Railway PostgreSQL & Docker support.
"""
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "production"
    APP_URL: str = "https://your-app.up.railway.app"
    SECRET_KEY: str = "supersecretkey_change_in_production"
    PORT: int = 8000
    
    # Database Config (Supports Railway DATABASE_URL)
    DB_URL: Optional[str] = Field(default=None, alias="DATABASE_URL")
    USE_SQLITE: bool = False
    SQLITE_DB_PATH: str = "bot_database.db"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres_password"
    POSTGRES_DB: str = "railway"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    
    @property
    def CLEAN_BOT_TOKEN(self) -> str:
        if not self.BOT_TOKEN:
            return ""
        return self.BOT_TOKEN.strip().strip('"').strip("'").strip()

    @property
    def CLEAN_APP_URL(self) -> str:
        if not self.APP_URL:
            return ""
        return self.APP_URL.strip().strip('"').strip("'").rstrip('/')

    @property
    def DATABASE_URL(self) -> str:
        url = self.DB_URL
        if not url:
            if self.USE_SQLITE:
                return f"sqlite+aiosqlite:///{self.SQLITE_DB_PATH}"
            url = f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        
        url = url.strip().strip('"').strip("'").strip()
        # Railway & Cloud SQL automatically inject postgres:// or postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        
        # Clean sslmode query parameters if needed for asyncpg driver
        if "?sslmode=" in url or "&sslmode=" in url:
            import re
            url = re.sub(r'[?&]sslmode=[^&]+', '', url)
        return url

    # Redis Config
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    
    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # Telegram Bot
    BOT_TOKEN: str = "7849102948:AAH_x92JkL0mN81qZ-eRtY5uP3wQ1vX9zAb"
    USE_WEBHOOK: bool = False
    WEBHOOK_SECRET: str = "my_webhook_secret_123"
    
    # Default Admin Group ID for Sales Alerts
    DEFAULT_ADMIN_GROUP_ID: str = "-100293847561"
    
    # Payme Credentials
    PAYME_MERCHANT_ID: str = "64d2910a9b3c4e5f6a7b8c9d"
    PAYME_KEY: str = "PaymeSecretKey123=="
    PAYME_TEST_KEY: str = "PaymeTestKey123=="
    
    # Click Credentials
    CLICK_MERCHANT_ID: str = "184920"
    CLICK_SERVICE_ID: str = "39201"
    CLICK_SECRET_KEY: str = "ClickSecretKey998877"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
