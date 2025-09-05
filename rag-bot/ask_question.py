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

# --- Конфигурация (без изменений) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AppConfig:
    def __init__(self):
        # Получаем директорию, где находится скрипт
        self.script_dir = Path(__file__).parent.absolute()
        load_dotenv(self.script_dir / ".env")  # Указываем путь к .env
        self.config = self._load_config()
        self.system_prompt = self._load_system_prompt()
        self.openai_client = self._setup_openai_client()
        self.gemini_client = self._setup_gemini_client()
    
    def _load_config(self) -> Dict[str, Any]:
        config_path = self.script_dir / "config.json"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Файл config.json не найден по пути: {config_path}")
            sys.exit(1)
        except json.JSONDecodeError:
            logger.error("Ошибка чтения JSON из config.json")
            sys.exit(1)
    
    def _load_system_prompt(self) -> str:
        prompt_path = self.script_dir / "system_prompt.txt"
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            logger.error(f"Файл system_prompt.txt не найден по пути: {prompt_path}")
            sys.exit(1)
    
    def _setup_openai_client(self) -> AsyncOpenAI:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("Переменная окружения OPENAI_API_KEY не установлена")
            return None
        return AsyncOpenAI(api_key=api_key)
    
    def _setup_gemini_client(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("Переменная окружения GEMINI_API_KEY не установлена")
            return None
        genai.configure(api_key=api_key)
        return genai

app_config = AppConfig()
app = FastAPI(title="Advanced OpenAI Gateway Service")

# --- Модели данных (без изменений) ---

class SourceChunk(BaseModel):
    text: str
    file: str

class RAGRequest(BaseModel):
    question: str
    context: List[SourceChunk]
    model_provider: str = None  # Optional override for model provider

class AnswerParagraph(BaseModel):
    paragraph: str
    source: SourceChunk

class AnswerResponse(BaseModel):
    answer: List[AnswerParagraph]
    model_used: str

class ModelStatus(BaseModel):
    provider: str
    model_name: str
    available: bool
    error: Optional[str] = None

class AvailableModelsResponse(BaseModel):
    models: List[ModelStatus]
    default_provider: str

# --- Эндпоинты API ---

class AIService:
    def __init__(self, config: AppConfig):
        self.config = config
    
    def _build_user_prompt(self, question: str, context: List[SourceChunk]) -> str:
        context_parts = []
        for i, chunk in enumerate(context):
            context_parts.append(f"ФРАГМЕНТ {i+1} (ИСТОЧНИК: {chunk.file}):\n{chunk.text}")
        
        formatted_context = "\n---\n".join(context_parts)
        return f"КОНТЕКСТ:\n---\n{formatted_context}\n---\nВОПРОС: {question}"
    
    async def generate_answer(self, question: str, context: List[SourceChunk], model_provider: str = None) -> tuple[List[Dict[str, Any]], str]:
        provider = model_provider or self.config.config.get("model_provider", "openai")
        
        if provider == "openai":
            return await self._generate_openai_answer(question, context)
        elif provider == "gemini":
            return await self._generate_gemini_answer(question, context)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Неподдерживаемый провайдер модели: {provider}"
            )
    
    async def _generate_openai_answer(self, question: str, context: List[SourceChunk]) -> tuple[List[Dict[str, Any]], str]:
        if not self.config.openai_client:
            raise HTTPException(
                status_code=500,
                detail="OpenAI клиент не настроен. Проверьте OPENAI_API_KEY."
            )
        
        model_name = self.config.config.get("openai_model", "gpt-4o")
        user_prompt = self._build_user_prompt(question, context)
        
        try:
            response = await self.config.openai_client.chat.completions.create(
                model=model_name,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": self.config.system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.config.config.get("temperature", 0.1),
            )
            raw_answer = response.choices[0].message.content
            
            try:
                parsed_json = json.loads(raw_answer)
                
                # Случай 1: Правильный формат (список объектов)
                if isinstance(parsed_json, list):
                    return parsed_json, model_name
                
                # Случай 2: Ответ обернут в ключ "answer"
                elif isinstance(parsed_json, dict) and "answer" in parsed_json and isinstance(parsed_json["answer"], list):
                    return parsed_json["answer"], model_name

                # Случай 3: Модель вернула один объект вместо списка
                elif isinstance(parsed_json, dict) and "paragraph" in parsed_json and "source" in parsed_json:
                    logger.warning("LLM вернула один объект вместо списка. Оборачиваю его в список.")
                    return [parsed_json], model_name
                
                # Запасной вариант для других неожиданных структур
                else:
                    logger.warning(f"LLM вернула неожиданную JSON-структуру: {raw_answer}")
                    return [], model_name

            except json.JSONDecodeError:
                logger.error(f"Не удалось декодировать JSON от LLM: {raw_answer}")
                return [], model_name

        except Exception as e:
            logger.error(f"Ошибка при обращении к OpenAI: {e}")
            raise HTTPException(
                status_code=500, 
                detail="Внутренняя ошибка сервера. Не удалось обработать запрос OpenAI."
            )
    
    async def _generate_gemini_answer(self, question: str, context: List[SourceChunk]) -> tuple[List[Dict[str, Any]], str]:
        if not self.config.gemini_client:
            raise HTTPException(
                status_code=500,
                detail="Gemini клиент не настроен. Проверьте GEMINI_API_KEY."
            )
        
        user_prompt = self._build_user_prompt(question, context)
        model_name = self.config.config.get("gemini_model", "gemini-1.5-flash")
        
        try:
            model = self.config.gemini_client.GenerativeModel(model_name)
            
            full_prompt = f"{self.config.system_prompt}\n\n{user_prompt}"
            
            response = await model.generate_content_async(
                full_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=self.config.config.get("temperature", 0.1)
                )
            )
            
            raw_answer = response.text
            
            try:
                parsed_json = json.loads(raw_answer)
                
                if isinstance(parsed_json, list):
                    return parsed_json, model_name
                elif isinstance(parsed_json, dict) and "answer" in parsed_json and isinstance(parsed_json["answer"], list):
                    return parsed_json["answer"], model_name
                elif isinstance(parsed_json, dict) and "paragraph" in parsed_json and "source" in parsed_json:
                    logger.warning("Gemini вернула один объект вместо списка. Оборачиваю его в список.")
                    return [parsed_json], model_name
                else:
                    logger.warning(f"Gemini вернула неожиданную JSON-структуру: {raw_answer}")
                    return [], model_name

            except json.JSONDecodeError:
                logger.error(f"Не удалось декодировать JSON от Gemini: {raw_answer}")
                return [], model_name
            
        except Exception as e:
            logger.error(f"Ошибка при обращении к Gemini: {e}")
            raise HTTPException(
                status_code=500, 
                detail="Внутренняя ошибка сервера. Не удалось обработать запрос Gemini."
            )
    
    def get_model_status(self) -> List[ModelStatus]:
        models = []
        
        # Check OpenAI status
        openai_error = None
        openai_available = bool(self.config.openai_client)
        if not openai_available:
            openai_error = "OPENAI_API_KEY не установлен"
        
        models.append(ModelStatus(
            provider="openai",
            model_name=self.config.config.get("openai_model", "gpt-4o"),
            available=openai_available,
            error=openai_error
        ))
        
        # Check Gemini status
        gemini_error = None
        gemini_available = bool(self.config.gemini_client)
        if not gemini_available:
            gemini_error = "GEMINI_API_KEY не установлен"
        
        models.append(ModelStatus(
            provider="gemini",
            model_name=self.config.config.get("gemini_model", "gemini-1.5-flash"),
            available=gemini_available,
            error=gemini_error
        ))
        
        return models

ai_service = AIService(app_config)

@app.post("/generate_answer", response_model=AnswerResponse)
async def generate_answer(request: RAGRequest):
    """
    Принимает вопрос и контекст, асинхронно обращается к AI модели и возвращает ответ.
    Поддерживает OpenAI GPT и Google Gemini модели.
    """
    answer_list, model_used = await ai_service.generate_answer(
        request.question, 
        request.context, 
        request.model_provider
    )
    return {"answer": answer_list, "model_used": model_used}

@app.get("/models", response_model=AvailableModelsResponse)
async def get_available_models():
    """
    Возвращает информацию о доступных AI моделях и их статусе.
    """
    models = ai_service.get_model_status()
    default_provider = app_config.config.get("model_provider", "openai")
    
    return AvailableModelsResponse(
        models=models,
        default_provider=default_provider
    )

# --- Запуск приложения (без изменений) ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)