# syntax=docker/dockerfile:1

# --- Stage 1: Build tools & C-extension compilation ---
FROM debian:trixie-slim AS builder

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

WORKDIR /build
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install build tools, compilers, header files, and extraction tools
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        unzip \
        build-essential \
        libvips-dev \
        libmagic-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy uv executable
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Provision free-threaded Python (3.14t) into /opt/venv
RUN uv venv /opt/venv --python 3.14t

# Install Deno
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local/deno sh && \
    chmod -R 755 /usr/local/deno

# Install Poetry using uv pip into /opt/venv and compile project dependencies
RUN uv pip install "poetry==$POETRY_VERSION"
COPY pyproject.toml poetry.lock* ./
RUN poetry install --without dev --no-root --no-interaction --no-ansi


# --- Stage 2: Production Runtime ---
FROM debian:trixie-slim AS runner

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    PYTHONMALLOC=malloc \
    PYTHONNODEBUG=1 \
    PYTHONOPTIMIZE=1 \
    DENO_INSTALL="/usr/local/deno" \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:/usr/local/deno/bin:$PATH"

WORKDIR /app
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install only shared runtime libraries and tools (no compilers or -dev packages)
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        nodejs \
        procps \
        libvips42 \
        libmagic1 \
        file \
        nginx \
        gettext-base \
        wget \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m bot

# Copy pre-built CPython binaries, compiled virtualenv, and Deno
COPY --from=builder /opt/python /opt/python
COPY --from=builder --chown=bot:bot /opt/venv /opt/venv
COPY --from=builder /usr/local/deno /usr/local/deno

# Copy application source code and prepare executable
COPY --chown=bot:bot . .
RUN chmod +x start.sh && chown -R bot:bot /app

# Change user
USER bot

# Run app
CMD ["./start.sh"]
