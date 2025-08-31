from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Loads and validates application settings for the GM Worker from environment variables.
    """
    # Load environment variables from a .env file
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # PostgreSQL Database URL
    DATABASE_URL: str

    # RabbitMQ Connection URL (for Celery broker)
    RABBITMQ_URL: str
    
    # ChromaDB Vector Store URL
    CHROMADB_HOST: str
    CHROMADB_PORT: int

    # Google Gemini API Key
    GEMINI_API_KEY: str

# Create a single, importable instance of the settings
settings = Settings()