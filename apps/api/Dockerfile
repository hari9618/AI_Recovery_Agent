# syntax=docker/dockerfile:1.7
# Build from the repository root:  docker build -f apps/api/Dockerfile .
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
# Same layout as the repo so data/knowledge and evals/ resolve relative to the app.
WORKDIR /srv/apps/api

FROM base AS deps
COPY apps/api/pyproject.toml apps/api/uv.lock ./
# The Ragas/LangChain eval extra is for running `python -m evals.run` locally; the API never imports it.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

FROM base AS runtime
RUN useradd --create-home --uid 10001 app
COPY --from=deps /srv/apps/api/.venv /srv/apps/api/.venv
COPY apps/api/ /srv/apps/api/
COPY data/ /srv/data/
COPY evals/ /srv/evals/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
ENV PATH="/srv/apps/api/.venv/bin:$PATH" MODEL_CACHE_DIR=/srv/.cache/models
# Bake the local embedding + reranker models into the image (no network needed at runtime).
RUN python -c "from app.rag.models import get_embedder, get_reranker; get_embedder().embed_query('warm'); get_reranker().score('warm', ['up'])" \
    && chown -R app:app /srv
COPY docker/api-entrypoint.sh /usr/local/bin/api-entrypoint
RUN chmod +x /usr/local/bin/api-entrypoint
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD python -c "import os,sys,urllib.request; p=os.environ.get('PORT','8000'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+p+'/api/v1/health').status==200 else 1)"
# The entrypoint runs migrations, then uvicorn on $PORT when the platform sets one (Render, Railway, Fly), else 8000.
ENTRYPOINT ["api-entrypoint"]
