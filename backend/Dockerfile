# Multi-stage: dependencies are built once and only the installed virtualenv is copied
# into the runtime image, so compilers never ship to production.
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# gcc is needed to build a few wheels; it stays in this stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Which vendor SDK to install. requirements.txt carries only the Anthropic client, so an
# image built with the default and then run with LLM_PROVIDER=gemini raised
# "The 'google-genai' package is not installed" on the first question — after a clean
# build and a successful start. pyproject declares the extras; nothing was installing them.
#
# Kept as a build arg rather than adding every SDK to requirements.txt so an image still
# ships one vendor client, which is the reason the extras exist.
ARG LLM_PROVIDER=anthropic

COPY requirements.txt pyproject.toml ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt \
    && case "$LLM_PROVIDER" in \
         openai)    /opt/venv/bin/pip install 'openai>=1.40' ;; \
         gemini)    /opt/venv/bin/pip install 'google-genai>=1.0' ;; \
         anthropic) : ;; \
         *) echo "Unknown LLM_PROVIDER '$LLM_PROVIDER' (anthropic|openai|gemini)" >&2; exit 1 ;; \
       esac


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# libpq for psycopg and curl for the healthcheck. No compiler in the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Run unprivileged. The previous image ran everything as root.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 6001

# /health is liveness only and never touches the database, so a database blip does not
# make the orchestrator kill an otherwise healthy process.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:6001/health || exit 1

# A real server: multiple workers, no --reload. uvicorn's worker class under gunicorn
# adds process supervision and graceful restarts.
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:6001", \
     "--timeout", "180", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
