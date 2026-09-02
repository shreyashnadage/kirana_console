from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    redis_url: str = "redis://redis:6379/0"
    neonize_url: str = "http://neonize:9999"

    anthropic_api_key: str
    sarvam_api_key: str

    owner_wa_jid: str          # 91XXXXXXXXXX@s.whatsapp.net
    assistant_wa_jid: str = "" # filled after first QR pair

    brief_time_utc: str = "03:30"          # HH:MM in UTC
    daily_cost_ceiling_usd: float = 2.00

    class Config:
        env_file = ".env"


settings = Settings()
