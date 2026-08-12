# syntax=docker/dockerfile:1

FROM python:3.14.7-slim-bookworm AS builder

# Set system, python, pip & poetry env
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
    POETRY_VERSION=2.2.1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR='/tmp/poetry_cache' \
    DENO_INSTALL="/usr/local/deno" \
    PATH="/usr/local/deno/bin:$PATH"

# Create workdir
WORKDIR /app

# Set shell to bash and enable pipefail
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Create user bot
RUN useradd -m bot

# Install dependencies needed to download and unzip Deno
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip build-essential python3-dev libvips-dev \
    ffmpeg nodejs procps libvips42 libmagic-dev \
    file nginx gettext-base wget netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Install Deno
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local/deno sh && \
    chmod -R 755 /usr/local/deno && \
    rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

# Copy dependencies first
COPY pyproject.toml poetry.lock* ./

# Install dependencies
RUN poetry config virtualenvs.create false && \
    poetry install --without dev --no-root --no-interaction --no-ansi

# Copy code
COPY --chown=bot:bot . .

# Make start script executable
RUN chmod +x start.sh

# Own /app folder as a whole
RUN chown -R bot:bot /app

# Change user
USER bot

# Run app
CMD ["./start.sh"]
