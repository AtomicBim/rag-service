"""
Конфигурационные параметры для сервиса индексации.
"""
import os
import logging

# === Параметры Qdrant ===
QDRANT_HOST: str = os.getenv("QDRANT_HOST", "192.168.42.188")
QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "internal_regulations_v2")

# === Параметры сервиса эмбеддингов ===
EMBEDDING_SERVICE_URL: str = os.getenv("EMBEDDING_SERVICE_URL", "http://rag-embedding:8001/create_embedding")
EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "1024"))

# === Параметры обработки документов ===
DOCS_ROOT_PATH: str = os.getenv("DOCS_ROOT_PATH", "/app/rag-source") # Путь внутри контейнера
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "60"))
BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "32")) # Уменьшим батч для API

# === Параметры логирования ===
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT: str = os.getenv(
    "LOG_FORMAT",
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

def setup_logging(name: str = __name__) -> logging.Logger:
    """Настройка единого логирования для всех модулей."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper()),
        format=LOG_FORMAT,
        force=True
    )
    return logging.getLogger(name)
