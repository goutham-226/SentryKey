from functools import lru_cache
from pydantic_settings import BaseSettings,SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env",extra="ignore") #parses and matches data from .env file
    database_url: str
    replicate_api_token: str
    openai_api_key: str
    anthropic_api_key: str
    google_api_key: str
    anthropic_system_prompt: str
    default_monthly_quota: int = 100000
    # a 'Reserved' row older than this is treated as abandoned by a dead worker and released.
    # must outlast the longest live request -> a request that settles after its row was released still records its real usage.
    reservation_timeout_minutes: int = 15
    # how often each app process sweeps for abandoned reservations.
    reservation_sweep_interval_seconds: int = 60

@lru_cache #caches the object and returns the stored object without having to create a new object for every func call.
def get_settings() -> Settings:
    return Settings()

