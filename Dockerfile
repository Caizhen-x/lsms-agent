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
    "anthropic>=0.40.0" \
    "chainlit>=1.3.0" \
    "pandas>=2.2" \
    "pyarrow>=17.0" \
    "pyreadstat>=1.2.7" \
    "python-dotenv>=1.0" \
    "ipython>=8.30" \
    "matplotlib>=3.9" \
    "seaborn>=0.13" \
    "numpy>=2.0" \
    "scipy>=1.13" \
    "statsmodels>=0.14" \
    "linearmodels>=6.0" \
    "pypdf>=5.0"

# Application code
COPY server/ ./server/
COPY ingest/ ./ingest/

# Pre-built catalog (parquet + variables index).  This is what the agent serves.
# Build it locally with `make all-ingest` before `docker build` / before pushing to HF.
COPY catalog/ ./catalog/

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
