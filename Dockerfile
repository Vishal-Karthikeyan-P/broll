FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-dev.txt requirements-whisper.txt ./
# Tests are shipped in the image so `docker compose run api pytest` works with no extra setup.
RUN pip install --no-cache-dir -r requirements-dev.txt
ARG WITH_WHISPER=0
RUN if [ "$WITH_WHISPER" = "1" ]; then pip install --no-cache-dir -r requirements-whisper.txt; fi
COPY . .
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD curl -fs http://localhost:8000/ready || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
