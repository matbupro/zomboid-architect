# =============================================================================
# ingestor/Dockerfile — Service d'ingestion multi-format pour Zomboid Knowledge Engine
# =============================================================================

FROM python:3.12-slim AS base

# ------------------------------------------------------------------------------
# System dependencies (FFmpeg, tesseract OCR, Playwright browsers)
# ------------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    # FFmpeg pour extraction vidéo/audio/frames
    ffmpeg \
    # Tesseract OCR pour images/scans (eng + fra)
    tesseract-ocr \
    libtesseract-dev \
    # Playwright dependencies
    libglib2.0-0 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    libxi6 \
    libxss1 \
    wget \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------------------------
# Python packages
# ------------------------------------------------------------------------------
WORKDIR /app/ingestor

# Copier d'abord les requirements pour caching du layer pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Installer Playwright Chromium dans le container Docker
RUN playwright install chromium

# ------------------------------------------------------------------------------
# Tesseract OCR data (français + anglais)
# ------------------------------------------------------------------------------
RUN tesseract --list-langs 2>/dev/null | grep -q 'eng' || \
    apt-get update && apt-get install -y tesseract-ocr-eng tesseract-ocr-fra && \
    rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------------------------
# Copy application code
# ------------------------------------------------------------------------------
COPY . .

WORKDIR /app

# ---------------------------------------------------------------------------
# Entrypoint : par défaut lance le CLI, mais peut être overwritten
# ---------------------------------------------------------------------------
ENTRYPOINT ["python", "-m", "ingestor.cli"]
