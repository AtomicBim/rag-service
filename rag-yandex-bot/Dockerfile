# Yandex Messenger Bot Service
# Lightweight Python service for bot API interaction

FROM python:3.11-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy service code
COPY . /app/

# Create directories
RUN mkdir -p /app/uploads /app/results

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose port (for health checks)
EXPOSE 8003

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8003/health || exit 1

# Run the bot
CMD ["python", "bot.py"]
