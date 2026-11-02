# syntax=docker/dockerfile:1

# ---- Build stage: install the backend and its dependencies into a venv ----
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /src
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install .

# (M2 adds a Node stage here that builds frontend/ and copies dist/ into the runtime image.)

# ---- Runtime stage ----
FROM python:3.12-slim
ARG APP_VERSION=dev
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION} \
    DATA_DIR=/data

RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --home-dir /home/app --create-home app \
 && mkdir -p /data && chown app:app /data

COPY --from=build /opt/venv /opt/venv

LABEL org.opencontainers.image.title="study-companion" \
      org.opencontainers.image.description="Self-hosted study companion (syncs from Moodle) with a remote MCP connector for Claude" \
      org.opencontainers.image.source="https://github.com/tkint/study-companion"

USER app
WORKDIR /home/app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"]

# Only reachable inside the Docker network; Caddy terminates HTTPS in front of it.
CMD ["uvicorn", "app.main:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
