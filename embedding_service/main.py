import os
import logging
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from dotenv import load_dotenv

# --- Конфигурация ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Загружаем переменные окружения (например, из .env файла, смонтированного в Docker)
load_dotenv()

# --- Настройка клиента OpenAI ---
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    logger.error("Переменная окружения OPENAI_API_KEY не установлена. Сервис не может стартовать.")
    openai_client = None
else:
    # Клиент OpenAI будет использовать прокси из окружения (HTTPS_PROXY)
    openai_client = AsyncOpenAI(api_key=api_key)

# Модель для эмбеддингов от OpenAI
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSION = 1024

# --- FastAPI приложение ---
app = FastAPI(
    title="OpenAI Embedding Service",
    description="Сервис для создания векторных представлений текста с использованием OpenAI API",
    version="1.2.0"
)

# --- Модели данных Pydantic ---
class TextRequest(BaseModel):
    text: str = Field(
        ...,
        description="Текст для векторизации",
        min_length=1,
        example="Пример текста для векторизации"
    )

class EmbeddingResponse(BaseModel):
    embedding: List[float] = Field(..., description="Векторное представление текста")
    dimension: int = Field(..., description="Размерность вектора")
    model_used: str = Field(..., description="Использованная модель эмбеддингов")

class HealthResponse(BaseModel):
    status: str
    model_used: str

# --- API эндпоинты ---
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Проверка состояния сервиса."""
    return {"status": "healthy" if openai_client else "unhealthy", "model_used": EMBEDDING_MODEL}

@app.post("/create_embedding",
          response_model=EmbeddingResponse,
          status_code=status.HTTP_200_OK)
async def create_embedding(request: TextRequest):
    """Принимает текст и возвращает его векторное представление от OpenAI."""
    if not openai_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI клиент не настроен. Проверьте OPENAI_API_KEY."
        )
    
    try:
        logger.info(f"Создание эмбеддинга для текста длиной {len(request.text)} символов с размерностью {EMBEDDING_DIMENSION}")
        
        # Вызов API OpenAI
        response = await openai_client.embeddings.create(
            input=[request.text.replace("\n", " ")], # OpenAI рекомендует заменять newlines
            model=EMBEDDING_MODEL,
            dimensions=EMBEDDING_DIMENSION
        )
        
        embedding = response.data[0].embedding
        dimension = len(embedding)
        
        logger.info(f"Эмбеддинг успешно создан с размерностью {dimension}")
        
        return {
            "embedding": embedding,
            "dimension": dimension,
            "model_used": EMBEDDING_MODEL
        }
        
    except Exception as e:
        logger.error(f"Ошибка при создании эмбеддинга через OpenAI: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обработки запроса в OpenAI: {str(e)}"
        )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8001))
    logger.info(f"Запуск сервиса эмбеддингов на 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
