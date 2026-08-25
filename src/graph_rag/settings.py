from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme-local-dev"

    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8765
    mcp_auth_token: str | None = None

    # BAAI/bge-small-en-v1.5 default (Phase 2+ Enricher) — 384 dimensions.
    embedding_dimensions: int = 384
    embedding_similarity_function: str = "cosine"


settings = Settings()
