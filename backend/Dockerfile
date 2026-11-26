# Babybabel API — production image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user. /app/data holds uploads when STORAGE_BACKEND=local
# (mounted as a volume in deploy/docker-compose.yml).
RUN useradd --system --uid 10001 --home /app app \
    && mkdir -p /app/data/uploads \
    && chown -R app /app/data
USER app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/api/', timeout=4).status == 200 else 1)"

# One worker on purpose: rate limits and the background jobs live in-process.
# Scale up by moving the rate limiter to Redis first (see README → Before going live).
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1", "--no-server-header"]
