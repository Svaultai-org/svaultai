FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system --gid 1001 bridge \
    && useradd --system --uid 1001 --gid bridge \
        --home-dir /app --shell /usr/sbin/nologin bridge

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt
COPY --chown=bridge:bridge __init__.py main.py protocol.py publisher.py \
    ./google_play_billing_bridge/

USER bridge
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn google_play_billing_bridge.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
