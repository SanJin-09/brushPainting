FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY services/api/requirements.txt /tmp/requirements-api.txt
COPY services/worker/requirements.txt /tmp/requirements-worker.txt
COPY services/model_runtime/requirements.txt /tmp/requirements-runtime.txt
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com --extra-index-url https://download.pytorch.org/whl/cu124 --trusted-host download.pytorch.org -r /tmp/requirements-api.txt -r /tmp/requirements-worker.txt -r /tmp/requirements-runtime.txt

COPY . /app

ENV PYTHONPATH=/app/services/api:/app/services/worker:/app/services/model_runtime

CMD ["uvicorn", "services.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
