# Stage 1: Build the React frontend
FROM node:20-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm test && npm run build

# Stage 2: Minimal Python runtime (non-root)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHAT_DB_PATH=/data/chat.db \
    CHAT_UPLOAD_DIR=/data/uploads

RUN groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser && \
    mkdir -p /app /data/uploads && \
    chown -R appuser:appuser /app /data

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser chat/ ./chat/
COPY --chown=appuser:appuser chat_server.py chat_client.py web_app.py ./
COPY --from=frontend-build --chown=appuser:appuser /build/frontend/dist ./frontend/dist

USER appuser
VOLUME ["/data"]
EXPOSE 8080 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=3)"

CMD ["python", "web_app.py", "--tcp-host", "127.0.0.1", "--tcp-port", "8765", "--web-host", "0.0.0.0", "--web-port", "8080"]
