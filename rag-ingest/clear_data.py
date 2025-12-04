import os
import sys
import logging
from pathlib import Path
from qdrant_client import QdrantClient
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load env
# Assumes script is in rag-ingest/
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")

# Configuration
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "internal_regulations_v2")
DB_PATH = os.getenv("INGEST_DB_PATH", "/app/state/ingest_state.db")

def get_qdrant_client():
    # Try environment variables first
    host = os.getenv("QDRANT_HOST", "localhost")
    port_str = os.getenv("QDRANT_PORT", "6333")
    port = int(port_str) if port_str else 6333
    
    clients_to_try = [
        (host, port),
        ("localhost", 6390), # Common local mapping
        ("localhost", 6333),
    ]
    
    for h, p in clients_to_try:
        try:
            logger.info(f"Attempting to connect to Qdrant at {h}:{p}...")
            client = QdrantClient(host=h, port=p, timeout=5)
            # Check connection
            client.get_collections()
            logger.info(f"Connected to Qdrant at {h}:{p}")
            return client
        except Exception as e:
            logger.warning(f"Failed to connect to {h}:{p}: {e}")
            
    return None

def clear_qdrant():
    client = get_qdrant_client()
    if not client:
        logger.error("Could not connect to Qdrant. Aborting.")
        return

    try:
        client.delete_collection(COLLECTION_NAME)
        logger.info(f"Collection '{COLLECTION_NAME}' deleted successfully.")
    except Exception as e:
        # It might error if collection doesn't exist
        logger.warning(f"Error deleting collection '{COLLECTION_NAME}' (it might not exist): {e}")

def clear_db():
    # Resolve DB path relative to project root if it's a relative path
    if not os.path.isabs(DB_PATH):
        # Clean up path to avoid ././
        clean_path = DB_PATH.replace("./", "")
        db_full_path = project_root / clean_path
    else:
        db_full_path = Path(DB_PATH)
        
    if db_full_path.exists():
        try:
            os.remove(db_full_path)
            logger.info(f"Database file '{db_full_path}' removed successfully.")
        except Exception as e:
            logger.error(f"Error removing database file '{db_full_path}': {e}")
    else:
        logger.info(f"Database file '{db_full_path}' not found.")

if __name__ == "__main__":
    print(f"Target Collection: {COLLECTION_NAME}")
    print(f"Target DB: {DB_PATH}")
    
    if len(sys.argv) > 1 and sys.argv[1] == "--force":
        confirm = 'y'
    else:
        confirm = input("Are you sure you want to clear the vector DB and ingestion state? (y/n): ")
    
    if confirm.lower() == 'y':
        clear_qdrant()
        clear_db()
        logger.info("Cleanup complete.")
    else:
        logger.info("Operation cancelled.")
