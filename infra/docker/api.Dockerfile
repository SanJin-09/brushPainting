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

COPY services/api/requirements.txt /tmp/requirements-api.txt
RUN pip install --no-cache-dir --retries 30 --timeout 1200 \
    -i https://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com \
    -r /tmp/requirements-api.txt

COPY . /app

ENV PYTHONPATH=/app

CMD ["sh", "-c", "exec uvicorn services.api.app.main:app --host \"${API_LISTEN_HOST:-127.0.0.1}\" --port \"${APP_PORT:-8000}\""]
