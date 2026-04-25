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

# Force single-threaded numpy/OpenBLAS at the OS level — prevents deadlock on Render
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV NUMEXPR_NUM_THREADS=1

# --timeout 120  : give scoring + DB fetch up to 2 min before Gunicorn kills the worker
# --keep-alive 5 : sensible keepalive for Render's load balancer
# -w 1           : single worker — Render free tier has ~512MB RAM, more workers = OOM
CMD ["sh", "-c", "gunicorn -w 1 -k uvicorn.workers.UvicornWorker --timeout 120 --keep-alive 5 app.main:app --bind 0.0.0.0:${PORT:-10000}"]