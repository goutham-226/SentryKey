from functools import lru_cache
from pydantic_settings import BaseSettings,SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env",extra="ignore") #parses and matches data from .env file
    database_url: str
    default_monthly_quota: int = 100000

@lru_cache #caches the object and returns the stored object without having to create a new object for every func call.
def get_settings() -> Settings:
    return Settings()

