FROM python:3.12-slim-bookworm
COPY docker/certs/ /usr/local/share/ca-certificates/vahan/
RUN /usr/sbin/update-ca-certificates
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY apps/api-server/pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install --upgrade "pip>=26.2,<27" \
    && pip install -r /tmp/requirements.txt "setuptools>=68" \
    && useradd --create-home --uid 10001 vahan
COPY apps/api-server/app ./app
RUN pip install --no-deps --no-build-isolation .
COPY apps/api-server/alembic.ini ./
COPY apps/api-server/migrations ./migrations
# Packaging tools are needed during the build only. Their vendored libraries
# are not part of the API runtime or the one-shot database provisioner.
RUN python -m pip uninstall --yes pip setuptools
USER vahan
EXPOSE 8000
CMD ["uvicorn", "app.main:application", "--host", "0.0.0.0", "--port", "8000"]
