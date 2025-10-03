FROM python:3.9-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование скриптов и документов
COPY . .

# Запуск скрипта индексации
CMD ["python", "upload.py"]
