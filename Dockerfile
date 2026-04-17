# Use a Python base image
FROM python:3.11-slim

# Install basic system dependencies (Removed Chrome to save 400MB+ RAM!)
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the spaCy model directly via pip
RUN pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1.tar.gz

# Copy the rest of your application code
COPY . .

# Start the application using gunicorn with exactly 1 worker to prevent OOM crashes
# We use $PORT so Render can dynamically assign the port it needs
CMD ["sh", "-c", "gunicorn -w 1 -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:${PORT:-10000}"]