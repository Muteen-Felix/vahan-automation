FROM docker.io/library/python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
COPY docker/certs/ /usr/local/share/ca-certificates/vahan/
RUN /usr/sbin/update-ca-certificates
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY apps/api-server/requirements.lock ./requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip pip install --require-hashes -r requirements.lock \
    && useradd --create-home --uid 10001 vahan
COPY apps/api-server/app ./app
COPY apps/api-server/alembic.ini ./
COPY apps/api-server/migrations ./migrations
# The Python installer is only needed to install the hash-locked dependencies.
RUN python -m pip uninstall --yes pip
# Declared build provenance (T29): supplied by the build, so `docker image inspect` shows the revision the image
# was declared to be built from. It is not proof of the image bytes (docs/release/pins.md).
ARG VCS_REF=unknown
ARG VERSION=unknown
LABEL org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.version=$VERSION
USER vahan
EXPOSE 8000
CMD ["uvicorn", "app.main:application", "--host", "0.0.0.0", "--port", "8000"]
