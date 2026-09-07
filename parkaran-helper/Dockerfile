FROM python:3.13-slim

WORKDIR /app

# Install Python deps. No build-essential needed anymore — torch is gone;
# chromadb + onnxruntime ship prebuilt wheels.
COPY requirements.txt requirements.lock .
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock gunicorn==23.0.0

# Pre-warm the ONNX all-MiniLM-L6-v2 model into the image cache so the
# container never needs network at runtime to embed search queries. Without
# this, the first semantic search would block ~10s downloading the model.
RUN python -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()(['warmup'])"

# Copy application code
COPY app.py wsgi.py config.py release.py ./
COPY api/ api/
COPY database/ database/
COPY enrichment/ enrichment/
COPY llm/ llm/
COPY templates/ templates/
COPY static/ static/

# Copy prebuilt data (baked into image)
ARG DATA_DIR=data
COPY ${DATA_DIR}/draft_vocabulary.json ${DATA_DIR}/sggs_all_shabads.json ${DATA_DIR}/tag_vocabulary.json ${DATA_DIR}/concept_tags.json ${DATA_DIR}/similarity_graph.json ${DATA_DIR}/sggs_sources.json ${DATA_DIR}/shabad_cache.db ${DATA_DIR}/release-manifest.json ${DATA_DIR}/concept_review.json data/
COPY ${DATA_DIR}/chroma_db/ data/chroma_db/
RUN python release.py verify data > /dev/null

ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=20s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5050/health/ready')"
EXPOSE 5050

CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--workers", "1", "--threads", "2", "--timeout", "120", "wsgi:app"]
