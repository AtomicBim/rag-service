import os
from dotenv import load_dotenv

load_dotenv()

QDRANT_HOST = os.getenv("QDRANT_HOST", "192.168.42.188")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "internal_regulations_v2")
SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", 5))

EMBEDDING_SERVICE_ENDPOINT = os.getenv("EMBEDDING_SERVICE_ENDPOINT", "http://192.168.45.63:8001/create_embedding")
OPENAI_API_ENDPOINT = os.getenv("RAG_BOT_ENDPOINT", "http://rag-bot:8000/generate_answer")