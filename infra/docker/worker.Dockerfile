FROM python:3.11-slim

ARG http_proxy
ARG https_proxy
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG no_proxy
ARG NO_PROXY

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    http_proxy=${http_proxy} \
    https_proxy=${https_proxy} \
    HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    no_proxy=${no_proxy} \
    NO_PROXY=${NO_PROXY} \
    PIP_DEFAULT_TIMEOUT=1200

WORKDIR /app

RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    git \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY services/api/requirements.txt /tmp/requirements-api.txt
COPY services/worker/requirements.txt /tmp/requirements-worker.txt
COPY services/model_runtime/requirements.txt /tmp/requirements-runtime.txt

RUN pip install --no-cache-dir --retries 30 --timeout 1200 \
    -i https://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com \
    --extra-index-url https://download.pytorch.org/whl/cu124 --trusted-host download.pytorch.org \
    -r /tmp/requirements-api.txt -r /tmp/requirements-worker.txt -r /tmp/requirements-runtime.txt

COPY . /app

ENV PYTHONPATH=/app/services/api:/app/services/worker:/app/services/model_runtime

CMD ["celery", "-A", "services.worker.celery_app.celery_app", "worker", "-Q", "default", "--loglevel=info"]
