FROM python:3.13-slim

WORKDIR /app

# Install Python deps. No build-essential needed anymore — torch is gone;
# chromadb + onnxruntime ship prebuilt wheels.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Pre-warm the ONNX all-MiniLM-L6-v2 model into the image cache so the
# container never needs network at runtime to embed search queries. Without
# this, the first semantic search would block ~10s downloading the model.
RUN python -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()(['warmup'])"

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
