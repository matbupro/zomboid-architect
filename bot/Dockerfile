# =============================================================================
# Dockerfile — Image du bot Discord Zomboid Knowledge Engine
# =============================================================================

# --- Builder : installe les deps dans une image temporaire -------------------
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Runtime ------------------------------------------------------------------
FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/ElChibros/Zomboid_Architect"
LABEL maintainer="ElChibros"

# WORKDIR parent du package "bot" → pour que "-m bot.main" marche
WORKDIR /app

# Chemin PYTHONPATH : ajoute /app au module search path
ENV PYTHONPATH=/app

# Copie de builder : libs + binaires
COPY --from=builder /usr/local/lib/python3.12/site-packages \
    /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Le contexte de build est ./bot → tout arrive dans /app/bot/
COPY . ./bot/

EXPOSE 8080

CMD ["python", "-m", "bot.main"]
