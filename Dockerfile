# syntax=docker/dockerfile:1

# Zeroth, we get deno binary

FROM denoland/deno:bin-2.6.5 AS deno_binary

# First, we build

FROM python:3.14.2-trixie AS builder

# Enable pipefail
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

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

# Update cutl and get node.js
RUN apt-get update && apt-get install -y --no-install-recommends git curl && \
    curl -fsSL https://deb.nodesource.com/setup_25.x | bash - && \
    apt-get install --no-install-recommends -y nodejs

# Build the POT provider script
RUN git clone --single-branch --branch 1.2.2 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil
WORKDIR /opt/bgutil/server
RUN npm install && npx tsc

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
RUN --mount=type=cache,target=$POETRY_CACHE_DIR \
    poetry install --without dev --no-root --no-interaction --no-ansi

# Second, run

FROM python:3.14.2-trixie AS runner

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

# Copy deno
COPY --from=deno_binary /deno /usr/local/bin/deno

WORKDIR /app

# Copy bgutil
COPY --from=builder /opt/bgutil/server /app/bgutil

# Copy dependencies
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

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

# Install Netdata
RUN wget -O /tmp/netdata-kickstart.sh https://get.netdata.cloud/kickstart.sh \
    && sh /tmp/netdata-kickstart.sh --non-interactive --stable-channel --disable-telemetry

# Copy code
COPY . .

# Copy NGINX
COPY nginx.conf.template /etc/nginx/nginx.conf.template

# Expose 8080/TCP port
EXPOSE 8080/tcp

# Make start script executable
RUN chmod +x start.sh

# Check versions
RUN apt list --installed
RUN deno --version && node --version && poetry --version

# Run app
CMD ["./start.sh"]
