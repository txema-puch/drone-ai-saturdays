from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENSKY_USERNAME: str
    OPENSKY_PASSWORD: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    class Config:
        env_file = ".env"
        extra = "ignore"  # tolerate cycle-N supabase vars and other ad-hoc env additions


settings = Settings()
