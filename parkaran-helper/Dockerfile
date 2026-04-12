FROM python:3.13-slim

WORKDIR /app

# Install system deps for sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY app.py wsgi.py config.py ./
COPY api/ api/
COPY database/ database/
COPY enrichment/ enrichment/
COPY llm/ llm/
COPY templates/ templates/
COPY static/ static/

# Copy prebuilt data (baked into image)
COPY data/ data/

ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

EXPOSE 5050

CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--workers", "1", "--threads", "2", "--timeout", "120", "wsgi:app"]
