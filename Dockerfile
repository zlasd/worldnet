FROM python:3.11-slim

ARG AGENTLY_CLI_VERSION=1.0.6
ARG DEBIAN_MIRROR=deb.debian.org
ARG DEBIAN_SECURITY_MIRROR=security.debian.org
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG NPM_REGISTRY=https://registry.npmjs.org

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    NPM_CONFIG_REGISTRY=${NPM_REGISTRY} \
    NPM_CONFIG_UPDATE_NOTIFIER=false

RUN find /etc/apt -type f \( -name "sources.list" -o -name "*.sources" \) -print0 \
    | xargs -0 sed -i \
        -e "s|http://deb.debian.org/debian|http://${DEBIAN_MIRROR}/debian|g" \
        -e "s|http://security.debian.org/debian-security|http://${DEBIAN_SECURITY_MIRROR}/debian-security|g" \
        -e "s|http://deb.debian.org/debian-security|http://${DEBIAN_SECURITY_MIRROR}/debian-security|g" \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates fonts-wqy-zenhei nodejs npm \
    && npm install -g "@tencent-qqmail/agently-cli@${AGENTLY_CLI_VERSION}" \
    && mkdir -p /var/lib/worldnet \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY app ./app
COPY config ./config
COPY migrations ./migrations
COPY scripts ./scripts

RUN pip install --upgrade pip && pip install .

EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
