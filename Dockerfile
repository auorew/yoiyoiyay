# syntax=docker/dockerfile:1

FROM python:3.14-trixie AS builder

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    PYTHONMALLOC=malloc \
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

# Create workdir
WORKDIR /app

# Set shell to bash and enable pipefail
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        unzip \
        build-essential \
        libvips-dev \
        libmagic-dev \
        ffmpeg \
        nodejs \
        procps \
        file \
        nginx \
        gettext-base \
        wget \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Install Deno
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local/deno sh && \
    chmod -R 755 /usr/local/deno && \
    rm -rf /var/lib/apt/lists/*

# Install Poetry and project dependencies
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

# Copy dependencies first
COPY pyproject.toml poetry.lock* ./

# Install dependencies
RUN poetry install --without dev --no-root --no-interaction --no-ansi \
    && rm -rf /tmp/poetry_cache /root/.cache

# Create non-root user and setup application source
RUN useradd -m bot

# Copy application source code and prepare executable
COPY --chown=bot:bot . .

# Make start script executable, own /app folder as a whole
RUN chmod +x start.sh && chown -R bot:bot /app

# Change user
USER bot

# Run app
CMD ["./start.sh"]
