"""
Yandex Messenger Bot
Main bot entry point with polling and file processing
"""
import os
import sys
import asyncio
import logging
import aiohttp
from typing import Dict, List, Optional
from dotenv import load_dotenv

from yandex_api import YandexMessengerClient
# from workflow import FileProcessor # Keeping these for now if needed, but RAG is priority
# from email_sender import EmailSender
from health_server import start_health_server
# from llm_integration import create_llm_keyboard, request_analysis

from qdrant_client import QdrantClient
from openai import AsyncOpenAI

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Start health check server
start_health_server(port=8003)
logger.info("Health check server started on port 8003")

# Configuration
YANDEX_BOT_TOKEN = os.getenv("YANDEX_BOT_TOKEN")
if not YANDEX_BOT_TOKEN:
    logger.error("YANDEX_BOT_TOKEN not set")
    sys.exit(1)

# RAG Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "internal_regulations_v2")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_EMBEDDING_MODEL = os.getenv("OPENROUTER_EMBEDDING_MODEL", "google/gemini-embedding-001")
RAG_BOT_ENDPOINT = os.getenv("RAG_BOT_ENDPOINT", "http://rag-bot:8000/generate_answer")
SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", 5))

# Clients
qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
openai_client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1"
) if OPENROUTER_API_KEY else None

# Track processing state per chat
processing_chats: Dict[str, bool] = {}

# Track last processed JSON file path per chat (for LLM callbacks)
last_json_files: Dict[str, str] = {}

# Track hash -> filename mapping for short callback_data
file_hash_mapping: Dict[str, str] = {}

# Track completed analyses per file_hash: {file_hash: set(analysis_types)}
completed_analyses: Dict[str, set] = {}


async def handle_file_message(client: YandexMessengerClient, message: dict):
    """
    Handle incoming file message from user

    Args:
        client: Yandex API client
        message: Message dict with file info
    """
    # Yandex API: chat_id can be in different places depending on API response structure
    chat_info = message.get("chat", {})
    chat_id = chat_info.get("chat_id") if isinstance(chat_info, dict) else None

    # For private chats, use login from 'from' field
    if not chat_id and "from" in message and chat_info.get("type") == "private":
        chat_id = message.get("from", {}).get("login")

    message_id = message.get("message_id")

    if not chat_id:
        logger.error(f"No chat_id in message: {message}")
        return

    # Check if already processing for this chat
    if processing_chats.get(chat_id, False):
        await client.send_message(
            chat_id,
            "⏳ Обработка предыдущего файла ещё не завершена. Пожалуйста, подождите."
        )
        return

    # Mark chat as processing
    processing_chats[chat_id] = True

    try:
        # Get file info
        file_info = message.get("file") or message.get("voice")
        if not file_info:
            await client.send_message(chat_id, "❌ Файл не найден в сообщении.")
            return  # Will trigger finally block

        # Yandex API can use either "file_id" or "id" field
        file_id = file_info.get("file_id") or file_info.get("id")
        file_name = file_info.get("name") or file_info.get("filename", "unknown")

        logger.info(f"Received file from chat {chat_id}: {file_name} (ID: {file_id})")

        # Send initial status
        await client.send_message(
            chat_id,
            f"📥 Получен файл: {file_name}\n🔄 Начинаю обработку..."
        )

        # Download file
        file_path = await client.download_file(file_id, file_name)
        if not file_path:
            await client.send_message(chat_id, "❌ Не удалось скачать файл.")
            return  # Will trigger finally block

        logger.info(f"File downloaded to: {file_path}")

        # Initialize processor
        processor = FileProcessor(
            audio_extractor_url=AUDIO_EXTRACTOR_URL,
            speech_recognition_url=SPEECH_RECOGNITION_URL
        )

        # Process file with status updates
        async def status_callback(status: str):
            """Send status updates to user"""
            await client.send_message(chat_id, status)

        result = await processor.process_file(file_path, file_name, status_callback)

        if result["status"] == "success":
            # Extract user email from message (from Yandex login)
            user_email = message.get("from", {}).get("login")

            if not user_email:
                logger.error(f"Cannot extract user email from message: {message}")
                await client.send_message(
                    chat_id,
                    "❌ Не удалось определить ваш email адрес для отправки результата."
                )
                return  # Will trigger finally block

            # Save JSON to shared volume for LLM analysis
            import json
            import hashlib
            json_dir = "/app/shared/transcripts"
            os.makedirs(json_dir, exist_ok=True)

            # Create unique filename
            base_name = os.path.splitext(file_name)[0]
            json_filename = f"{base_name}_transcript.json"
            json_path = os.path.join(json_dir, json_filename)

            try:
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(result["result"], f, ensure_ascii=False, indent=2)
                logger.info(f"Transcript saved to: {json_path}")

                # Store JSON path for this chat (for LLM callbacks)
                last_json_files[chat_id] = json_path

                # Store hash mapping for short callback_data
                file_hash = hashlib.md5(json_filename.encode()).hexdigest()[:8]
                file_hash_mapping[file_hash] = json_path
                logger.debug(f"Hash mapping: {file_hash} -> {json_path}")
            except Exception as e:
                logger.error(f"Failed to save transcript JSON: {e}")

            # Send success message
            metadata = result["result"]["metadata"]
            await client.send_message(
                chat_id,
                f"✅ Обработка завершена!\n\n"
                f"📊 Статистика:\n"
                f"⏱ Время обработки: {metadata['processing_time']}\n"
                f"🎙 Сегментов: {metadata['num_segments']}\n"
                f"👥 Спикеров: {metadata['num_speakers']}\n"
                f"📝 Символов текста: {metadata['total_text_length']}\n\n"
                f"📧 Отправляю результат на {user_email}..."
            )

            # Send result via email to user's address
            email_sender = EmailSender()
            email_sent = await email_sender.send_result(
                result["result"],
                file_name,
                user_email
            )

            if not email_sent:
                await client.send_message(
                    chat_id,
                    "⚠️ Не удалось отправить email с результатом."
                )
            else:
                await client.send_message(
                    chat_id,
                    f"✅ Email с результатом успешно отправлен на {user_email}!"
                )

                # Add LLM analysis keyboard (optional feature)
                keyboard = create_llm_keyboard(json_path, file_hash)
                await client.send_message(
                    chat_id,
                    "🤖 Хотите дополнительный анализ с помощью AI?\n\n"
                    "Выберите тип анализа:",
                    inline_keyboard=keyboard
                )

        else:
            # Send error message
            await client.send_message(
                chat_id,
                f"❌ Ошибка обработки:\n{result.get('error', 'Unknown error')}"
            )

    except Exception as e:
        logger.error(f"Error handling file message: {e}", exc_info=True)
        await client.send_message(
            chat_id,
            f"❌ Произошла ошибка: {str(e)}"
        )

    finally:
        # Release processing lock
        processing_chats[chat_id] = False


async def handle_callback_query(client: YandexMessengerClient, callback_query: dict):
    """
    Handle inline keyboard button callback (Stub for RAG bot)
    """
    chat_id = callback_query.get("from", {}).get("login")
    if chat_id:
        await client.send_message(chat_id, "⚠️ Эта функция временно недоступна в режиме RAG-бота.")


async def handle_text_message(client: YandexMessengerClient, message: dict):
    """
    Handle incoming text message from user (RAG Chat)
    """
    # Yandex API: chat_id can be in different places depending on API response structure
    chat_info = message.get("chat", {})
    chat_id = chat_info.get("chat_id") if isinstance(chat_info, dict) else None

    # For private chats, use login from 'from' field
    if not chat_id and "from" in message and chat_info.get("type") == "private":
        chat_id = message.get("from", {}).get("login")

    text = message.get("text", "")

    if not chat_id:
        return

    # Handle commands
    if text.startswith("/start") or text.startswith("/help"):
        await client.send_message(
            chat_id,
            "👋 Привет! Я RAG-бот для поиска по ВНД.\n\n"
            "❓ Задайте мне любой вопрос по внутренним документам, и я найду ответ.\n"
            "📂 База знаний обновляется автоматически."
        )
        return

    # RAG Logic
    try:
        await client.send_message(chat_id, "🔍 Ищу информацию...")
        
        # 1. Get Embedding
        if not openai_client:
            await client.send_message(chat_id, "❌ Ошибка: OpenAI клиент не настроен.")
            return

        embedding_resp = await openai_client.embeddings.create(
            model=OPENROUTER_EMBEDDING_MODEL,
            input=text
        )
        question_embedding = embedding_resp.data[0].embedding

        # 2. Search Qdrant
        search_results = qdrant_client.search(
            collection_name=QDRANT_COLLECTION_NAME,
            query_vector=question_embedding,
            limit=SEARCH_LIMIT,
            with_payload=True
        )

        if not search_results:
            await client.send_message(chat_id, "⚠️ К сожалению, я не нашел информации по вашему вопросу в базе знаний.")
            return

        # Prepare context
        context = [
            {"text": result.payload['text'], "file": result.payload.get('source_file', 'unknown')}
            for result in search_results
        ]
        
        # 3. Call RAG-Bot (LLM)
        payload = {
            "question": text,
            "context": context,
            "model_provider": "openai"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(RAG_BOT_ENDPOINT, json=payload, timeout=60) as response:
                if response.status == 200:
                    result = await response.json()
                    answer = result.get("answer", "Пустой ответ от LLM")
                    
                    # 4. Send Answer
                    final_message = answer
                    await client.send_message(chat_id, final_message)
                else:
                    error_text = await response.text()
                    logger.error(f"RAG-Bot error: {error_text}")
                    await client.send_message(chat_id, "❌ Ошибка при генерации ответа.")

    except Exception as e:
        logger.error(f"Error in RAG flow: {e}", exc_info=True)
        await client.send_message(chat_id, "❌ Произошла внутренняя ошибка.")


async def main():
    """
    Main bot loop with polling
    """
    logger.info("Starting Yandex Messenger Bot (RAG Mode)...")
    logger.info(f"RAG Endpoint: {RAG_BOT_ENDPOINT}")
    logger.info(f"Qdrant: {QDRANT_HOST}:{QDRANT_PORT}")

    # Clear any stale processing states from previous crash/restart
    processing_chats.clear()
    logger.info("Cleared processing state cache")

    # Initialize client
    client = YandexMessengerClient(YANDEX_BOT_TOKEN)

    # Test connection
    if not await client.test_connection():
        logger.error("Failed to connect to Yandex Messenger API")
        return

    logger.info("Bot started successfully. Polling for updates...")

    offset = 0

    try:
        while True:
            try:
                # Get updates
                updates = await client.get_updates(offset=offset, limit=10)

                if not updates:
                    await asyncio.sleep(1)
                    continue

                for update in updates:
                    # Log raw update for debugging
                    logger.info(f"Raw update received: {update}")

                    # Update offset
                    update_id = update.get("update_id", 0)
                    offset = max(offset, update_id + 1)

                    message = update.get("message", update)

                    # Check for text message
                    if "text" in message:
                        asyncio.create_task(handle_text_message(client, message))
                    elif "file" in message or "voice" in message:
                         # Stub for file handling if dependencies are missing
                         chat_id = message.get("from", {}).get("login")
                         if chat_id:
                             await client.send_message(chat_id, "⚠️ Обработка файлов временно отключена.")
                    elif "callback_data" in message:
                        asyncio.create_task(handle_callback_query(client, message))

            except Exception as e:
                logger.error(f"Error in polling loop: {e}", exc_info=True)
                await asyncio.sleep(5)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")


if __name__ == "__main__":
    asyncio.run(main())
