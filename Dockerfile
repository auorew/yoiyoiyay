# syntax=docker/dockerfile:1

FROM python:3.14.3-slim-bookworm AS builder

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
    POETRY_CACHE_DIR='/tmp/poetry_cache'

# Create workdir
WORKDIR /app

# Set shell to bash and enable pipefail
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install dependencies needed to download and unzip Deno
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Deno
RUN curl -fsSL https://deno.land/x/install/install.sh | sh
# Add Deno to the PATH so yt-dlp can call it
ENV DENO_INSTALL="/root/.deno"
ENV PATH="$DENO_INSTALL/bin:$PATH"

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libvips-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

# Copy dependencies first
COPY pyproject.toml poetry.lock* ./

# Install dependencies
RUN poetry config virtualenvs.create false && \
    poetry install --without dev --no-root --no-interaction --no-ansi

# Install runtimw dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    procps \
    libvips42 \
    libmagic-dev \
    file \
    nginx \
    gettext-base \
    wget \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copy code
COPY . .

# Make start script executable
RUN chmod +x start.sh

# Run app
CMD ["./start.sh"]
