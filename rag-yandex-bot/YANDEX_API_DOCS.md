# Yandex Messenger Bot API - Рабочая конфигурация

## Статус: ✅ РАБОТАЕТ

Последнее обновление: 2025-12-02

## Важные особенности Yandex Messenger Bot API

### 1. Приватные чаты vs Групповые чаты

#### Приватные чаты
- **Идентификатор**: `login` из поля `from.login` (формат email: `user@domain.ru`)
- **Отправка сообщений**: Использовать поле `"login"` в payload, НЕ `"chat_id"`

#### Групповые чаты
- **Идентификатор**: `chat_id` (числовой или специальный формат)
- **Отправка сообщений**: Использовать поле `"chat_id"` в payload

### 2. Структура обновлений (getUpdates)

Yandex API может возвращать обновления в **двух форматах**:

#### Формат 1: Вложенная структура
```json
{
  "update_id": 123,
  "message": {
    "chat": {...},
    "from": {...},
    "file": {...}
  }
}
```

#### Формат 2: Плоская структура (ТЕКУЩАЯ)
```json
{
  "update_id": 123,
  "chat": {"type": "private"},
  "from": {...},
  "file": {...}
}
```

**Решение**: Использовать `message = update.get("message", update)` для поддержки обоих форматов.

### 3. Поля файлов

Yandex API использует **непоследовательные названия полей**:

- File ID может быть в `file.id` ИЛИ `file.file_id`
- File name может быть в `file.name` ИЛИ `file.filename`

**Решение**: Использовать fallback:
```python
file_id = file_info.get("file_id") or file_info.get("id")
file_name = file_info.get("name") or file_info.get("filename", "unknown")
```

### 4. Формат File ID

File ID имеет формат: `disk/{uuid}`

Пример: `disk/c25f71db-7e44-47ce-8613-46d022ebf2dc`

**Важно**: При сохранении файла нужно санитизировать слеши:
```python
safe_file_id = file_id.replace("/", "_").replace("\\", "_")
```

## Реализованные методы API

### 1. getUpdates (Long Polling)

```python
async def get_updates(offset: int = 0, limit: int = 100, timeout: int = 60) -> List[Dict]
```

- **Метод**: `GET`
- **Endpoint**: `/bot/v1/messages/getUpdates/`
- **Параметры**: `offset`, `limit`, `timeout`
- **Timeout**: `timeout + 10` секунд для aiohttp
- **Возвращает**: `response["updates"]` или `None`

### 2. sendText (Отправка сообщений)

```python
async def send_message(chat_id: str, text: str) -> bool
```

- **Метод**: `POST`
- **Endpoint**: `/bot/v1/messages/sendText/`
- **Content-Type**: `application/json`

#### Payload для приватных чатов (email формат):
```json
{
  "login": "user@domain.ru",
  "text": "Сообщение"
}
```

#### Payload для групповых чатов:
```json
{
  "chat_id": "123456",
  "text": "Сообщение"
}
```

**Логика определения**: Проверяем `"@" in chat_id`

### 3. getFile (Скачивание файлов)

```python
async def download_file(file_id: str, file_name: str) -> Optional[str]
```

- **Метод**: `POST` (НЕ GET!)
- **Endpoint**: `/bot/v1/messages/getFile/`
- **Content-Type**: `application/json` (НЕ form-data!)

#### Payload:
```json
{
  "file_id": "disk/c25f71db-7e44-47ce-8613-46d022ebf2dc"
}
```

#### Response:
- **Status 200**: Binary file content (стрим)
- **Status != 200**: JSON с описанием ошибки

**Важно**:
- НЕ использовать `multipart/form-data`
- НЕ использовать `application/x-www-form-urlencoded`
- НЕ использовать Yandex Disk API (требует другие права доступа)

### 4. uploadFile & sendFile (Отправка файлов)

```python
async def send_file(chat_id: str, file_path: str, caption: Optional[str] = None) -> bool
```

#### Шаг 1: Загрузка файла
- **Метод**: `POST`
- **Endpoint**: `/bot/v1/files/upload/`
- **Content-Type**: `multipart/form-data`
- **Payload**: FormData с полем `file`

#### Шаг 2: Отправка файла в чат
- **Метод**: `POST`
- **Endpoint**: `/bot/v1/messages/sendFile/`
- **Content-Type**: `application/json`
- **Payload**:
```json
{
  "chat_id": "123456",
  "file_id": "полученный_file_id",
  "caption": "Опциональное описание"
}
```

## Аутентификация

Все запросы требуют заголовок:
```
Authorization: OAuth {YANDEX_BOT_TOKEN}
```

## Обработка ошибок

### Ошибка 404 chat_not_found
**Причина**: Использован `chat_id` вместо `login` для приватного чата

**Решение**: Проверить формат идентификатора (наличие `@`) и использовать правильное поле

### Ошибка 415 Content-Type not supported
**Причина**: Неправильный Content-Type для getFile

**Решение**: Использовать `application/json` для getFile, НЕ multipart

### Ошибка 403 DiskUnsupportedUserAccountTypeError
**Причина**: Попытка использовать Yandex Disk API вместо Bot API

**Решение**: Использовать `/bot/v1/messages/getFile/` вместо disk API

### Пустой ответ `{}`
**Причина**: Использован GET вместо POST для getFile

**Решение**: Использовать POST с JSON payload

## Извлечение chat_id из обновления

```python
# Получить информацию о чате
chat_info = message.get("chat", {})
chat_id = chat_info.get("chat_id") if isinstance(chat_info, dict) else None

# Для приватных чатов использовать login
if not chat_id and "from" in message and chat_info.get("type") == "private":
    chat_id = message.get("from", {}).get("login")
```

## Обработка пересланных сообщений (Forwarded Messages)

### Структура forwarded messages

Пересланные сообщения приходят в поле `forwarded_messages` (массив объектов Message).

**Ключевое отличие:**
- Прямое сообщение: `"file": {"id": "disk/...", "name": "..."}`
- Пересланное: `"forwarded_messages": [{"file": {"id": "disk/...", "name": "..."}}]`

### Пример JSON

```json
{
  "update_id": 1571249,
  "message_id": 1702329071098005,
  "chat": {"type": "private"},
  "from": {"login": "user@yandex.ru"},
  "forwarded_messages": [
    {
      "message_id": 1702323240544005,
      "from": {"display_name": "Ivan Ivanov"},
      "file": {
        "id": "disk/abc123",
        "name": "data.json",
        "size": 1024
      }
    }
  ]
}
```

### Обработка

```python
if "forwarded_messages" in message:
    for fwd_msg in message["forwarded_messages"]:
        if "file" in fwd_msg:
            file_id = fwd_msg["file"]["id"]
            filename = fwd_msg["file"]["name"]
            # Скачиваем файл через getFile
```

**Self-forward:** `forwarded_messages[0].from` содержит того же пользователя

## Проверенные сценарии

✅ Прием сообщений через long polling
✅ Парсинг плоской структуры обновлений
✅ Извлечение chat_id для приватных чатов
✅ Отправка текстовых сообщений в приватные чаты (через login)
✅ Скачивание файлов через POST + application/json
✅ Обработка file_id с префиксом `disk/`
✅ Санитизация file_id для файловой системы
✅ Обработка пересланных сообщений (forwarded_messages)

## Не протестировано

⚠️ Отправка сообщений в групповые чаты
⚠️ Отправка файлов обратно пользователю
⚠️ Голосовые сообщения (voice)
⚠️ Другие типы вложений (attachments)

## Пример успешного взаимодействия

```
[05:53:11] INFO: Raw update received
[05:53:11] INFO: Received file from chat r.grigoriev@atomsk.ru
[05:53:11] INFO: Sending message to r.grigoriev@atomsk.ru
[05:53:11] INFO: Message sent successfully
[05:53:11] INFO: Downloading file: disk/c25f71db-...
[05:53:12] INFO: File downloaded: /app/uploads/disk_c25f71db-..._file.aac
[05:53:12] INFO: Processing file...
```

## Зависимости

- `aiohttp` для async HTTP запросов
- OAuth токен бота через переменную окружения `YANDEX_BOT_TOKEN`

## База URL

```
https://botapi.messenger.yandex.net
```

## Рекомендации

1. Всегда проверяйте наличие `@` в идентификаторе для определения типа чата
2. Используйте fallback для названий полей (file_id/id, name/filename)
3. Санитизируйте file_id перед использованием в путях файловой системы
4. Для getFile ВСЕГДА используйте POST + application/json
5. Timeout для long polling должен быть >= 60 секунд
6. Добавляйте +10 секунд к timeout для aiohttp.ClientTimeout

## История изменений

### 2025-12-02
- ✅ Исправлена отправка сообщений в приватные чаты (login вместо chat_id)
- ✅ Исправлено скачивание файлов (POST + JSON вместо GET)
- ✅ Добавлен fallback для извлечения file_id и filename
- ✅ Добавлена санитизация file_id с слешами
- ✅ Исправлен парсинг плоской структуры обновлений
