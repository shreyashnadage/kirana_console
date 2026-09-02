FROM python:3.12-slim

# neonize bundles a Go binary via cffi; needs build tools the first time
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libc6-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY daemon.py .

# WA session credentials live in /app/session (bind-mounted volume)
ENV SESSION_PATH=/app/session

EXPOSE 9999

CMD ["python", "daemon.py"]
