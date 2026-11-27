# Dockerfile for Princess of Jannah 24/7 Cloud Production Engine
FROM python:3.11-slim

# Install system dependencies (FFmpeg for video mastering, curl, git, ca-certificates, Node.js 22 LTS for Baileys v7)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    ca-certificates \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements first for layer caching
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Install Node.js dependencies for Baileys WhatsApp Bot
COPY package.json package-lock.json* /app/
RUN npm install --production

# Copy application files
COPY . /app

# Normalize line endings and make entrypoint executable
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

EXPOSE 10000

CMD ["/app/entrypoint.sh"]
