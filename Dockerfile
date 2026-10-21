# Multi-stage Dockerfile for CampusMate
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runner
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r ./requirements.txt
RUN pip install --no-cache-dir openai

# Copy application source code under /app/campusmate so `campusmate` package resolves
WORKDIR /app/campusmate
COPY pyproject.toml pytest.ini __init__.py ./
COPY server/ ./server/
COPY agent/ ./agent/
COPY data/ ./data/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Initialize environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8000 8001

CMD ["python", "-m", "campusmate.server.app.main", "--host", "0.0.0.0", "--port", "8000"]
