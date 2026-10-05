FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH="/home/finsight/.local/bin:${PATH}"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential libpq-dev curl && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --shell /bin/bash finsight

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt && \
    python -m playwright install --with-deps chromium && \
    chmod -R a+rX /ms-playwright

COPY version.json ./version.json
COPY backend/alembic.ini .
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/docker/entrypoint.sh /prod-entrypoint.sh

RUN chmod +x /prod-entrypoint.sh && chown -R finsight:finsight /app /prod-entrypoint.sh

USER finsight

EXPOSE 8080

ENTRYPOINT ["/prod-entrypoint.sh"]
