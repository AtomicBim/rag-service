import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from root .env file
root_dir = Path(__file__).parent.parent
load_dotenv(root_dir / ".env")

# Qdrant Vector Database Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "192.168.42.188")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "internal_regulations_v2")
SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", "20"))

# External Services Configuration
EMBEDDING_SERVICE_HOST = os.getenv("EMBEDDING_SERVICE_HOST", "192.168.45.55")
EMBEDDING_SERVICE_PORT = os.getenv("EMBEDDING_SERVICE_PORT", "8001")
EMBEDDING_SERVICE_ENDPOINT = f"http://{EMBEDDING_SERVICE_HOST}:{EMBEDDING_SERVICE_PORT}/create_embedding"

# RAG Bot Service Configuration  
RAG_BOT_PORT = os.getenv("RAG_BOT_PORT", "8000")
OPENAI_API_ENDPOINT = f"http://rag-bot:{RAG_BOT_PORT}/generate_answer" 