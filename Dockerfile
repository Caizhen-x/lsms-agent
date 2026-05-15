# Container for the LSMS Agent — designed for Hugging Face Spaces (Docker SDK).
# Image expects three secrets at runtime: ANTHROPIC_API_KEY, GROUP_PASSWORD, CHAINLIT_AUTH_SECRET.
# Data (catalog/parquet) is baked into the image; rebuild after re-ingesting.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps — pyreadstat needs libreadstat at build time; the rest are minimal runtime libs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libreadstat-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps separately for better layer caching.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install \
    "anthropic==0.102.0" \
    "chainlit==2.11.0" \
    "pandas==3.0.3" \
    "pyarrow==24.0.0" \
    "pyreadstat==1.3.4" \
    "python-dotenv==1.2.2" \
    "ipython==9.13.0" \
    "matplotlib==3.10.9" \
    "seaborn==0.13.2" \
    "numpy==2.4.4" \
    "scipy==1.17.1" \
    "statsmodels==0.14.6" \
    "linearmodels==7.0" \
    "pypdf==6.11.0" \
    "rank-bm25==0.2.2" \
    "pyyaml==6.0.3"

# Application code
COPY server/ ./server/
COPY ingest/ ./ingest/

# Pre-built catalog (parquet, variables index, and docs index).  Built by
# `make all-ingest` locally before deployment.
COPY catalog/ ./catalog/

# Curated crosswalks (small YAML files).  Read at runtime.
COPY crosswalks/ ./crosswalks/

# Hugging Face Spaces convention: app listens on $PORT (default 7860).
# PYTHONPATH=/app makes `from server.foo import ...` resolve when Chainlit
# loads server/app.py as a script (bypassing the usual package machinery).
ENV PORT=7860 \
    PYTHONPATH=/app \
    CATALOG_DIR=/app/catalog \
    COUNTRY_DATA_DIR=/app/Country\ Data

EXPOSE 7860

# --headless avoids opening a browser; --host 0.0.0.0 binds outside the container.
CMD ["sh", "-c", "chainlit run server/app.py --host 0.0.0.0 --port ${PORT} --headless"]
