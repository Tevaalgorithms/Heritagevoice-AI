# One image, three commands: API (default), UI and worker (see deploy/docker-compose.yml).
# Pin base image digests before a release; tags are used here so the file stays readable.

FROM ghcr.io/astral-sh/uv:0.10.7 AS uv

FROM python:3.15-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.15-slim-bookworm
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --create-home --home-dir /home/hv hv
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY frontend ./frontend
COPY .streamlit/config.toml ./.streamlit/config.toml
USER hv
EXPOSE 8000 8501
# API by default. The UI and worker override the command in compose.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
