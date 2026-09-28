FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY pyproject.toml .
COPY src ./src
COPY scripts ./scripts
COPY docs ./docs
RUN pip install --no-deps -e . && useradd --uid 10001 --create-home appuser && mkdir -p data/processed data/raw artifacts && chown -R appuser:appuser /app
USER appuser
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=3)"
CMD ["python","-m","uvicorn","pipelinemedic.api:app","--host","0.0.0.0","--port","8765","--workers","1"]
