FROM python:3.9-slim

WORKDIR /app

# Установка LibreOffice для конвертации .doc файлов
RUN apt-get update && \
    apt-get install -y --no-install-recommends libreoffice-writer && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Установка зависимостей Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование скриптов и документов
COPY . .

# Запуск скрипта индексации
CMD ["python", "upload.py"]
