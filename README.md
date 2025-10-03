# RAG-Сервис для Работы с Внутренними Документами

## Описание

RAG-сервис (Retrieval-Augmented Generation) представляет собой систему для поиска и генерации ответов на основе внутренних документов организации. Система состоит из трех основных компонентов, работающих в Docker:

- **embedding-service** - сервис для создания векторных представлений (эмбеддингов) текста с использованием API OpenAI.
- **rag-bot** - бэкенд-сервис для генерации ответов с использованием OpenAI GPT или Google Gemini.
- **rag-chat** - фронтенд-интерфейс на базе Gradio для взаимодействия с пользователем.

## Архитектура системы

Новая архитектура полностью инкапсулирована в Docker, что исключает зависимость от внешних машин в локальной сети.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Docker-окружение                                                        │
│                                                                         │
│  ┌──────────────┐   HTTP   ┌───────────────────┐   HTTP   ┌───────────┐  │
│  │   rag-chat   │───► 1. ───┤ embedding-service │───► 2. ───┤ OpenAI    │  │
│  │ (Gradio UI)  │          │   (FastAPI)       │          │ API       │  │
│  │  Port: 7860  │          │    Port: 8001     │          │           │  │
│  └───────┬──────┘          └───────────────────┘          └───────────┘  │
│          │                                                              │
│          │ 3. Поиск в Qdrant                                            │
│          │                                                              │
│          ▼                                                              │
│  ┌──────────────┐   HTTP   ┌───────────────────┐   HTTP   ┌───────────┐  │
│  │   Qdrant DB  │◄─── 4. ───┤      rag-bot      │───► 5. ───┤ OpenAI/   │  │
│  │(Vector Store)│          │     (FastAPI)     │          │ Gemini    │  │
│  │192.168.42.188│          │     Port: 8000    │          │ API       │  │
│  └──────────────┘          └───────────────────┘          └───────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Компоненты системы

### 1. embedding-service (Сервис эмбеддингов)

**Файл:** `embedding_service/main.py`

Новый сервис на FastAPI, который предоставляет API для создания эмбеддингов текста. В отличие от предыдущей реализации, он использует облачную модель OpenAI (`text-embedding-3-small`), что снимает нагрузку с локального оборудования.

- **API-эндпоинт:** `POST /create_embedding`

### 2. rag-bot (Бэкенд-сервис)

**Файл:** `rag-bot/ask_question.py`

Бэкенд-сервис на FastAPI, который принимает вопрос и контекст, а затем генерирует ответ с помощью LLM (OpenAI или Gemini).

- **API-эндпоинт:** `POST /generate_answer`

### 3. rag-chat (Фронтенд-интерфейс)

**Файл:** `rag-chat/main_app.py`

Фронтенд-сервис на Gradio. Теперь он обращается к `embedding-service` внутри Docker-сети для векторизации вопроса.

#### Пошаговый процесс обработки запроса:

1.  **Получение эмбеддинга** - `rag-chat` отправляет вопрос в `embedding-service`.
2.  **Запрос к OpenAI** - `embedding-service` обращается к API OpenAI для получения вектора.
3.  **Поиск в Qdrant** - `rag-chat` ищет релевантные документы в Qdrant по вектору.
4.  **Формирование контекста и запрос к rag-bot** - `rag-chat` отправляет вопрос и найденный контекст в `rag-bot`.
5.  **Генерация ответа** - `rag-bot` генерирует ответ с помощью LLM.

## Конфигурационные файлы

### rag-chat/config.py (Обновлено)

```python
QDRANT_HOST = "192.168.42.188"
QDRANT_PORT = 6333
COLLECTION_NAME = "internal_regulations_v2"
SEARCH_LIMIT = 30

# Сервис эмбеддингов теперь доступен по имени контейнера в Docker
EMBEDDING_SERVICE_ENDPOINT = "http://embedding-service:8001/create_embedding" 
OPENAI_API_ENDPOINT = "http://rag-bot:8000/generate_answer"
```

## Docker-контейнеризация

### docker-compose.yml (Обновлено)

Основной файл для развертывания всей системы теперь включает `embedding-service`.

```yaml
version: '3.8'

services:
  rag-bot:
    build: ./rag-bot
    # ... (конфигурация без изменений)

  embedding-service:
    build: ./embedding_service
    container_name: embedding_service
    restart: unless-stopped
    ports:
      - "8001:8001"
    environment:
      - HTTPS_PROXY=socks5://172.17.0.1:10808
      - HTTP_PROXY=socks5://172.17.0.1:10808
      - NO_PROXY=localhost,127.0.0.1
      - PYTHONUNBUFFERED=1
    volumes:
      - ./rag-bot/.env:/app/.env:ro

  rag-chat:
    build: ./rag-chat
    container_name: rag_chat_service
    restart: unless-stopped
    ports:
      - "7860:7860"
    environment:
      # Исключения для Qdrant и внутренних сервисов
      - NO_PROXY=192.168.42.188,rag-bot,embedding-service
      - PYTHONUNBUFFERED=1
    depends_on:
      - rag-bot
      - embedding-service
```

## Зависимости

### embedding-service/requirements.txt (Новый)
- `fastapi`
- `uvicorn`
- `openai`
- `python-dotenv`

### rag-bot/requirements.txt
- `fastapi`, `uvicorn`, `openai`, `pydantic`, `python-dotenv`, `google-generativeai`, `httpx[socks]`

### rag-chat/requirements.txt
- `qdrant-client`, `requests`, `gradio`

## Установка и запуск

Процесс запуска остается прежним, но теперь система полностью самодостаточна и не требует запущенного `rag-client` на другой машине.

1.  **Настройте `rag-bot/.env`** с вашими API-ключами.
2.  **Запустите систему:**
    ```bash
    docker-compose up -d --build
    ```

### Доступ к сервисам

- **Gradio интерфейс:** http://localhost:7860
- **Документация rag-bot:** http://localhost:8000/docs
- **Документация embedding-service:** http://localhost:8001/docs

## Сетевая архитектура

### Прокси-настройки

- **rag-bot** и **embedding-service** используют SOCKS5 прокси для доступа к внешним API (OpenAI/Gemini).
- **rag-chat** теперь обращается к `rag-bot` и `embedding-service` по их именам, которые добавлены в переменную `NO_PROXY`.

### Внешние зависимости

1.  **Qdrant Vector Database:** `192.168.42.188:6333` (остается внешней зависимостью)
2.  **OpenAI/Gemini API** (доступ через VPN/прокси)

## Структура проекта (Обновлено)
```
rag-service/
├── docker-compose.yml
├── README.md
├── embedding_service/       # <-- НОВЫЙ СЕРВИС
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── rag-bot/
│   ├── ask_question.py
│   ├── config.json
│   ├── system_prompt.txt
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env (не версионируется)
└── rag-chat/
    ├── main_app.py
    ├── config.py
    ├── requirements.txt
    └── Dockerfile
```
