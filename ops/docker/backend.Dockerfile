# Imagen de la API: desarrollo local (docker compose up) y producción en Render (render.yaml)
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
RUN useradd --create-home api
# JULI y LUCIA guardan su estado en app/*/artifacts: el usuario de la API debe poder escribir ahí
COPY --chown=api:api app ./app
USER api
EXPOSE 8000
# PORT lo pone el hosting (Render); en local, 8000
CMD ["sh", "-c", "exec uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
