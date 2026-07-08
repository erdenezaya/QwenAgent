# Use official lightweight Python image
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY backend/ ./backend
COPY .env .env

# Expose FastAPI server port
EXPOSE 8000

# Set environment path
ENV PYTHONPATH=/app

# Start the web server
CMD ["python", "-m", "backend.main"]
