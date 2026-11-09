from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    TELEGRAM_BOT_TOKEN: str = "123456789:AAG_mock_token_for_testing_12345"

    OPENAI_API_KEY: str = "mock_openai_key"
    OPENAI_BASE_URL: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    WHISPER_MODEL: str = "whisper-1"

    GROQ_API_KEY: Optional[str] = None

    GOOGLE_SERVICE_ACCOUNT_FILE: str = "data/service_account.json"
    GOOGLE_SPREADSHEET_ID: Optional[str] = None
    GOOGLE_SHEET_NAME: str = "Лист1"
    GOOGLE_SHEET_URL: Optional[str] = None

    BITRIX24_WEBHOOK_URL: Optional[str] = None
    BITRIX24_RESPONSIBLE_ID: int = 1

    TIMEZONE: str = "Europe/Moscow"
    CACHE_TTL_SECONDS: int = 300
    FALLBACK_CSV_PATH: str = "data/sample_estimate.csv"

    @property
    def sheet_web_url(self) -> Optional[str]:
        if self.GOOGLE_SHEET_URL:
            return self.GOOGLE_SHEET_URL
        if self.GOOGLE_SPREADSHEET_ID:
            return f"https://docs.google.com/spreadsheets/d/{self.GOOGLE_SPREADSHEET_ID}/edit"
        return None

    @property
    def has_google_credentials(self) -> bool:
        return bool(
            self.GOOGLE_SPREADSHEET_ID
            and Path(self.GOOGLE_SERVICE_ACCOUNT_FILE).exists()
        )

    @property
    def has_bitrix24_credentials(self) -> bool:
        return bool(self.BITRIX24_WEBHOOK_URL and self.BITRIX24_WEBHOOK_URL.startswith("http"))

    @property
    def has_openai_credentials(self) -> bool:
        return bool(self.OPENAI_API_KEY and not self.OPENAI_API_KEY.startswith("mock_"))


settings = Settings()
