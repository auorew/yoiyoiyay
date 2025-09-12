# syntax=docker/dockerfile:1

FROM python:3.12-trixie AS base

# Set env
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
# Set python env
ENV PYTHONUNBUFFERED=1
ENV PYTHONFAULTHANDLER=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONHASHSEED=random
# Set pip env
ENV PIP_NO_CACHE_DIR=off
ENV PIP_DEFAULT_TIMEOUT=100
ENV PIP_DISABLE_PIP_VERSION_CHECK=on

# Create workdir
WORKDIR /app

# Install all the dependencies
RUN apt-get update && apt-get install -y \
    python3-dev \
    libmagic-dev file \
    ffmpeg yt-dlp \
    libvips42 libvips-dev

# Update pip
RUN python3 -m pip install --upgrade pip
RUN pip3 install --upgrade wheel setuptools

# Install poetry
RUN pip3 install poetry

# Copy files
COPY . .

# Install app dependencies
RUN poetry install --without dev --no-interaction --no-ansi

# Run app
CMD ["poetry", "run", "python3", "/app/main.py"]
