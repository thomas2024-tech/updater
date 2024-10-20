FROM python:3.9-slim

# Install necessary packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . ./