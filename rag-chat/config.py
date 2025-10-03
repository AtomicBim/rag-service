import os

QDRANT_HOST = os.getenv("QDRANT_HOST", "192.168.42.188")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "internal_regulations_v2")
SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", "30"))  # Лимит документов для проверки ответа

EMBEDDING_SERVICE_ENDPOINT = os.getenv("EMBEDDING_SERVICE_ENDPOINT", "http://rag-embedding:8001/create_embedding")
OPENAI_API_ENDPOINT = os.getenv("OPENAI_API_ENDPOINT", "http://rag-bot:8000/generate_answer") 
