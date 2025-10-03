# 1. Используем официальный легковесный образ Python
FROM mirror.gcr.io/library/python:3.11-slim-bullseye

# 2. Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# 3. Устанавливаем curl для healthcheck
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 4. Копируем файл с зависимостями
COPY requirements.txt .

# 5. Устанавливаем зависимости, не сохраняя кэш для уменьшения размера образа
RUN pip install --no-cache-dir -r requirements.txt

# 6. Копируем все остальные файлы проекта в контейнер
COPY . .

# 7. Сообщаем Docker, что контейнер будет слушать на порту 8001
EXPOSE 8001

# 8. Команда для запуска приложения при старте контейнера
CMD ["python", "main.py"]
