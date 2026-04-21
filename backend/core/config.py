from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENSKY_USERNAME: str
    OPENSKY_PASSWORD: str

    class Config:
        env_file = "backend/.env"


settings = Settings()
