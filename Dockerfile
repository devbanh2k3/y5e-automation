# ============================================================
# YouTube AI Automation — Dockerfile
# ============================================================

FROM node:20-bookworm-slim AS node_runtime

FROM python:3.12-slim AS base

# Prevent .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies needed by asyncpg/Pillow and Remotion rendering.
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev chromium && \
    rm -rf /var/lib/apt/lists/*

# Copy a pinned Node.js runtime from the official Node image without Debian npm's large dependency tree.
COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node_runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Remotion/video engine dependencies.
COPY video_engine/package.json video_engine/package-lock.json ./video_engine/
RUN cd video_engine && npm ci

# Copy application code
COPY . .

# Create output directory
RUN mkdir -p /app/output

# Expose FastAPI port
EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--log-level", "info"]
