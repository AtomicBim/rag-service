import os
import sys
import json
import hashlib
import sqlite3
import requests
import logging
import shutil
from pathlib import Path
from typing import List, Dict, Optional

from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models

# Load env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
DOCS_DIR = os.getenv("DOCS_DIR", "./data") 
DB_PATH = os.getenv("INGEST_DB_PATH", "./rag-ingest/ingest_state.db")

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "internal_regulations_v2")

# Embeddings Config
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
EMBEDDING_MODEL = os.getenv("OPENROUTER_EMBEDDING_MODEL", "google/gemini-embedding-001")

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100

# --- Database ---
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS files 
                 (path TEXT PRIMARY KEY, hash TEXT, last_updated TIMESTAMP)''')
    conn.commit()
    return conn

def get_file_hash(path: str) -> str:
    hasher = hashlib.md5()
    with open(path, 'rb') as f:
        buf = f.read()
        hasher.update(buf)
    return hasher.hexdigest()

# --- OpenAI Client for Embeddings (via OpenRouter) ---
if not OPENROUTER_API_KEY:
    logger.error("OPENROUTER_API_KEY is not set. Cannot generate embeddings.")
    sys.exit(1)

openai_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

# --- Embeddings ---
def get_embedding(text: str) -> Optional[List[float]]:
    try:
        # OpenRouter/OpenAI API call
        resp = openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text
        )
        return resp.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding error via OpenRouter (Model: {EMBEDDING_MODEL}): {e}")
        return None

# --- Qdrant ---
def get_qdrant_client():
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

def ensure_collection(client):
    try:
        client.get_collection(COLLECTION_NAME)
    except Exception:
        logger.info(f"Collection {COLLECTION_NAME} not found. Creating...")
        
        # Test embedding to get dim
        test_emb = get_embedding("test")
        if test_emb:
            dim = len(test_emb)
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE)
            )
            logger.info(f"Created collection with dimension {dim}")
        else:
            logger.error("Could not determine embedding dimension. Collection creation failed.")
            sys.exit(1)

def upload_chunks(client, chunks: List[str], source_file: str):
    points = []
    import uuid
    
    for i, text in enumerate(chunks):
        embedding = get_embedding(text)
        if not embedding:
            logger.warning(f"Skipping chunk {i} in {source_file} due to embedding failure.")
            continue
            
        points.append(models.PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                "text": text,
                "source_file": source_file,
                "chunk_index": i
            }
        ))
    
    if points:
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )
        logger.info(f"Uploaded {len(points)} chunks for {source_file}")

def delete_file_chunks(client, source_file: str):
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.Filter(
            must=[
                models.FieldCondition(
                    key="source_file",
                    match=models.MatchValue(value=source_file)
                )
            ]
        )
    )
    logger.info(f"Deleted old chunks for {source_file}")

# --- Parsing ---
def parse_docx(path: Path) -> str:
    import docx
    doc = docx.Document(path)
    return "\n".join([p.text for p in doc.paragraphs])

def parse_pdf(path: Path) -> str:
    import pypdf
    text = ""
    try:
        reader = pypdf.PdfReader(path)
        for page in reader.pages:
            text += page.extract_text() + "\n"
    except Exception as e:
        logger.error(f"Error parsing PDF {path}: {e}")
    return text

def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += (size - overlap)
    return chunks

# --- Main Loop ---
def process_docs(docs_dir: Path):
    conn = init_db()
    c = conn.cursor()
    client = get_qdrant_client()
    ensure_collection(client)
    
    # 1. Scan Files & Apply Priority
    files_map = {} 
    for root, dirs, files in os.walk(docs_dir):
        for f in files:
            path = Path(root) / f
            if f.lower().endswith(".docx"):
                files_map.setdefault(path.stem, {})["docx"] = path
            elif f.lower().endswith(".pdf"):
                files_map.setdefault(path.stem, {})["pdf"] = path
    
    # 2. Determine final list
    final_files = []
    for stem, variants in files_map.items():
        if "docx" in variants:
            final_files.append(variants["docx"])
            if "pdf" in variants:
                logger.info(f"Skipping PDF for {stem} because DOCX exists.")
        elif "pdf" in variants:
            final_files.append(variants["pdf"])

    # 3. Process
    for file_path in final_files:
        str_path = str(file_path)
        current_hash = get_file_hash(str_path)
        
        c.execute("SELECT hash FROM files WHERE path=?", (str_path,))
        row = c.fetchone()
        
        if row and row[0] == current_hash:
            logger.info(f"Skipping {file_path.name} (unchanged)")
            continue
            
        logger.info(f"Processing {file_path.name}...")
        
        text = ""
        if file_path.suffix.lower() == ".docx":
            text = parse_docx(file_path)
        elif file_path.suffix.lower() == ".pdf":
            text = parse_pdf(file_path)
            
        if not text.strip():
            logger.warning(f"No text extracted from {file_path}")
            continue
            
        chunks = chunk_text(text)
        
        if row:
            delete_file_chunks(client, file_path.name)
            
        upload_chunks(client, chunks, file_path.name)
        
        c.execute("INSERT OR REPLACE INTO files (path, hash, last_updated) VALUES (?, ?, CURRENT_TIMESTAMP)",
                  (str_path, current_hash))
        conn.commit()

    conn.close()
    logger.info("Ingestion complete.")

if __name__ == "__main__":
    target_dir = Path(DOCS_DIR)
    if not target_dir.exists():
        logger.warning(f"Docs dir {target_dir} does not exist.")
    else:
        process_docs(target_dir)
