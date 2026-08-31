# syntax=docker/dockerfile:1

FROM debian:trixie-slim

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHON_GIL=0 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    PYTHONNODEBUG=1 \
    PYTHONOPTIMIZE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    POETRY_VERSION=2.4.2 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR='/tmp/poetry_cache' \
    DENO_INSTALL="/usr/local/deno" \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:/usr/local/deno/bin:$PATH"

WORKDIR /app
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install build tools, native compilation libraries, and runtime utilities in a single layer
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        unzip \
        build-essential \
        cmake \
        libvips-dev \
        libmagic-dev \
        libpq-dev \
        ffmpeg \
        nodejs \
        procps \
        file \
        nginx \
        gettext-base \
        wget \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copy uv executable
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Provision free-threaded Python into /opt/venv
RUN uv venv /opt/venv --python 3.14t

# Install Deno
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local/deno sh && \
    chmod -R 755 /usr/local/deno

# Install Poetry and project dependencies, then purge build caches to minimize image size
RUN uv pip install "poetry==$POETRY_VERSION"
COPY pyproject.toml poetry.lock* ./
RUN poetry install --without dev --no-root --no-interaction --no-ansi \
    && rm -rf /tmp/poetry_cache /root/.cache

# Create non-root user and setup application source
RUN useradd -m bot

# Copy application source code and prepare executable
COPY --chown=bot:bot . .
RUN chmod +x start.sh && chown -R bot:bot /app

# Change user
USER bot

# Run app
CMD ["./start.sh"]
