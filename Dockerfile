# Railway image for the Piper Voices HTTP API.
# Installs piper-tts from PyPI (not a source build) and bakes in one small voice.

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    PIPER_VOICE=en_US-lessac-medium \
    PIPER_MODEL_DIR=/app/models \
    DOWNLOAD_MISSING_VOICE=false \
    MAX_CONCURRENT_TTS=1 \
    OMP_NUM_THREADS=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p "${PIPER_MODEL_DIR}" \
    && python -m piper.download_voices en_US-lessac-medium --download-dir "${PIPER_MODEL_DIR}"

COPY app ./app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health')"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
