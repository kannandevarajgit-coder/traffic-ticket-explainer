FROM python:3.12-slim

# Run as a non-root user (uid 1000). Hugging Face Spaces requires this, and it is safer everywhere.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    DOCQA_DATA_DIR=/home/user/app/data
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
COPY --chown=user . .
# Pre-download the local embedding model so the first question is fast.
RUN python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction as E; E()(['warm up'])"

EXPOSE 8501
# XSRF protection is off because hosted pages (e.g. Hugging Face Spaces) embed the app in an iframe,
# which otherwise blocks file uploads with a 403 error.
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.enableXsrfProtection=false", "--browser.gatherUsageStats=false"]
