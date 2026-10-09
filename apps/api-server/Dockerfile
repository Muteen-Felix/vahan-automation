FROM python:3.12-slim-trixie
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY apps/api-server/pyproject.toml apps/api-server/requirements.lock ./
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/pip pip install --require-hashes -r requirements.lock && useradd --create-home --uid 10001 vahan
COPY apps/api-server/app ./app
RUN pip install --no-deps .
COPY apps/api-server/alembic.ini ./
COPY apps/api-server/migrations ./migrations
USER vahan
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:application", "--host", "0.0.0.0", "--port", "8000"]
