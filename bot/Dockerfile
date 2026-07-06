FROM python:3.12-slim

WORKDIR /app

# System deps (minimal)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl tini && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source code
COPY . .

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "bot.main"]
