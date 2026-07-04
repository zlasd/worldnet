FROM python:3.11-slim

ARG AGENTLY_CLI_VERSION=1.0.6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NPM_CONFIG_UPDATE_NOTIFIER=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates nodejs npm \
    && npm install -g "@tencent-qqmail/agently-cli@${AGENTLY_CLI_VERSION}" \
    && mkdir -p /var/lib/worldnet \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY config ./config
COPY scripts ./scripts

RUN pip install --upgrade pip && pip install .

EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
