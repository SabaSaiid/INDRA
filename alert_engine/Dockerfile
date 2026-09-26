FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Ensure data directory exists
RUN mkdir -p data

EXPOSE 8001

# The start script can handle demo vs live modes, but for standard docker run:
CMD ["uvicorn", "alert_engine.main:app", "--host", "0.0.0.0", "--port", "8001"]
