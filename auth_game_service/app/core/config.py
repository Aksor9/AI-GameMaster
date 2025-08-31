from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Loads and validates application settings from environment variables.
    """
    # Load environment variables from a .env file
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # PostgreSQL Database URL
    DATABASE_URL: str

    # RabbitMQ Connection URL
    RABBITMQ_URL: str

    # JWT Settings for authentication
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

# Create a single, importable instance of the settings
# This was corrected from 'setting' to 'settings'.
settings = Settings()