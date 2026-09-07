from dataclasses import dataclass

@dataclass
class Settings():
    default_monthly_quota: int = 100000

def get_settings() -> Settings:
    return Settings()

