FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY apps/api-server/pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r /tmp/requirements.txt && useradd --create-home --uid 10001 vahan
COPY apps/api-server/app ./app
RUN pip install --no-deps .
COPY apps/api-server/alembic.ini ./
COPY apps/api-server/migrations ./migrations
USER vahan
EXPOSE 8000
CMD ["sh", "-c", "python -m app.migrate && exec uvicorn app.main:application --host 0.0.0.0 --port 8000"]
