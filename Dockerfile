FROM python:3.10-slim

WORKDIR /app

# Install system dependencies (libmagic, build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create required directories
RUN mkdir -p logs static/uploads/issues backups

EXPOSE 5000

ENV PYTHONUNBUFFERED=1

CMD ["python", "run.py"]
