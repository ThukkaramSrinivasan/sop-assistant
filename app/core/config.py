from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str

    # AI API keys
    openai_api_key: str
    anthropic_api_key: str

    # Auth
    jwt_secret: str
    jwt_algorithm: str = "HS256"

    # Model config
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "claude-sonnet-4-20250514"

    # Chunking
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 50

    # RAG
    rag_top_k: int = 5

    # Worker
    worker_poll_interval_seconds: int = 5


settings = Settings()
