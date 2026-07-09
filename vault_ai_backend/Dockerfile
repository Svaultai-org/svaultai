# VaultAI backend production image.
#
# Two stages: builder installs Python deps into a virtualenv;
# runtime copies the venv + app source into a slim image and runs
# uvicorn as a non-root user.
#
# Build:
#   docker build -t vaultai-backend:latest .
#
# Run (all secrets injected via env, never baked in):
#   docker run --rm \
#     --name vaultai-backend \
#     -p 8000:8000 \
#     -e VAULTAI_ENV=production \
#     -e VAULT_SESSION_SECRET=... \
#     -e DATABASE_URL=... \
#     -e OPENAI_API_KEY=... \
#     -e CORS_ALLOWED_ORIGIN_REGEX='^https://(app|www)\.svaultai\.com$|^https://svaultai\.com$' \
#     -e STRIPE_API_KEY=... -e STRIPE_WEBHOOK_SECRET=... \
#     -e VAULTAI_RATE_LIMIT_BACKEND=redis \
#     -e VAULTAI_RATE_LIMIT_REDIS_URL=... \
#     vaultai-backend:latest
#
# The image contains no .env, no .venv from the host, no test cache,
# and no secrets. See .dockerignore for the exclusion list.



FROM python:3.13-slim AS builder

WORKDIR /build




RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*



RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"



COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt




FROM python:3.13-slim AS runtime




RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        tesseract-ocr \
        curl \
    && rm -rf /var/lib/apt/lists/*



RUN groupadd --system --gid 1001 vaultai \
    && useradd  --system --uid 1001 --gid vaultai \
                --home-dir /app --shell /usr/sbin/nologin vaultai



COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app



COPY --chown=vaultai:vaultai . /app



USER vaultai



EXPOSE 8000



HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:8000/debug/ping" \
        || curl -fsS "http://127.0.0.1:8000/" \
        || exit 1



CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--workers", "2"]
