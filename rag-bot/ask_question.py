import os
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import AsyncOpenAI
import google.generativeai as genai
from dotenv import load_dotenv

# --- Конфигурация ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AppConfig:
    def __init__(self):
        self.script_dir = Path(__file__).parent.absolute()
        load_dotenv(self.script_dir / ".env")
        self.config = self._load_config()
        self.system_prompt = self._load_system_prompt()
        self.openai_client = self._setup_openai_client()
        self.gemini_client = self._setup_gemini_client()
    
    def _load_config(self) -> Dict[str, Any]:
        config_path = self.script_dir / "config.json"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Ошибка загрузки config.json: {e}")
            sys.exit(1)
    
    def _load_system_prompt(self) -> str:
        prompt_path = self.script_dir / "system_prompt.txt"
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError as e:
            logger.error(f"Ошибка загрузки system_prompt.txt: {e}")
            sys.exit(1)
    
    def _setup_openai_client(self) -> Optional[AsyncOpenAI]:
        # OpenRouter priority
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key:
            logger.info("Используется OpenRouter API")
            return AsyncOpenAI(
                api_key=openrouter_key,
                base_url="https://openrouter.ai/api/v1"
            )
        
        # Fallback to standard OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("Переменная окружения OPENAI_API_KEY (или OPENROUTER_API_KEY) не установлена")
            return None
        return AsyncOpenAI(api_key=api_key)
    
    def _setup_gemini_client(self) -> Optional[Any]:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("Переменная окружения GEMINI_API_KEY не установлена")
            return None
        genai.configure(api_key=api_key)
        return genai

app_config = AppConfig()
app = FastAPI(title="Plain Text RAG Answer Service")

# --- Обновленные модели данных ---

class SourceChunk(BaseModel):
    text: str
    file: str

class RAGRequest(BaseModel):
    question: str
    context: List[SourceChunk]
    model_provider: Optional[str] = None

# НОВАЯ, простая модель ответа
class PlainTextAnswerResponse(BaseModel):
    answer: str
    model_used: str

# --- Логика API ---

class AIService:
    def __init__(self, config: AppConfig):
        self.config = config
    
    def _build_user_prompt(self, question: str, context: List[SourceChunk]) -> str:
        context_parts = [f"ФРАГМЕНТ ИЗ ФАЙЛА '{chunk.file}':\n{chunk.text}" for chunk in context]
        formatted_context = "\n---\n".join(context_parts)
        return f"КОНТЕКСТ:\n---\n{formatted_context}\n---\nВОПРОС: {question}"
    
    async def _generate_openai_answer(self, question: str, context: List[SourceChunk]) -> tuple[str, str]:
        if not self.config.openai_client:
            raise HTTPException(status_code=500, detail="OpenAI/OpenRouter клиент не настроен.")
        
        # Приоритет env vars
        model_name = os.getenv("OPENROUTER_MODEL") or self.config.config.get("openai_model", "gpt-4o")
        temperature = float(os.getenv("LLM_TEMPERATURE") or self.config.config.get("temperature", 0.1))
        
        user_prompt = self._build_user_prompt(question, context)
        
        try:
            response = await self.config.openai_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": self.config.system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
            )
            # Просто берем текстовый ответ
            answer = response.choices[0].message.content
            return answer.strip(), model_name
        except Exception as e:
            logger.error(f"Ошибка при обращении к OpenAI/OpenRouter: {e}")
            raise HTTPException(status_code=500, detail="Ошибка обработки запроса OpenAI/OpenRouter.")

    async def _generate_gemini_answer(self, question: str, context: List[SourceChunk]) -> tuple[str, str]:
        if not self.config.gemini_client:
            raise HTTPException(status_code=500, detail="Gemini клиент не настроен.")
            
        model_name = self.config.config.get("gemini_model", "gemini-1.5-flash")
        user_prompt = self._build_user_prompt(question, context)
        full_prompt = f"{self.config.system_prompt}\n\n{user_prompt}"
        
        try:
            model = self.config.gemini_client.GenerativeModel(model_name)
            response = await model.generate_content_async(
                full_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=self.config.config.get("temperature", 0.1)
                )
            )
            return response.text.strip(), model_name
        except Exception as e:
            logger.error(f"Ошибка при обращении к Gemini: {e}")
            raise HTTPException(status_code=500, detail="Ошибка обработки запроса Gemini.")

    async def generate_answer(self, request: RAGRequest) -> PlainTextAnswerResponse:
        provider = request.model_provider or self.config.config.get("model_provider", "openai")
        
        if provider == "openai":
            answer_text, model_name = await self._generate_openai_answer(request.question, request.context)
        elif provider == "gemini":
            answer_text, model_name = await self._generate_gemini_answer(request.question, request.context)
        else:
            raise HTTPException(status_code=400, detail=f"Неподдерживаемый провайдер модели: {provider}")
        
        return PlainTextAnswerResponse(answer=answer_text, model_used=model_name)

ai_service = AIService(app_config)

@app.post("/generate_answer", response_model=PlainTextAnswerResponse)
async def generate_answer_endpoint(request: RAGRequest):
    return await ai_service.generate_answer(request)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
