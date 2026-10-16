# QC image: unlike apps/api-server/Dockerfile this one is self-contained for qc-agent (build, run, nothing else), so it
# carries its own PostgreSQL. The binaries are copied from the same pinned official image that compose.yaml and CI use.
FROM docker.io/library/postgres:17.11-bookworm@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826 AS postgres
FROM docker.io/library/python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
COPY docker/certs/ /usr/local/share/ca-certificates/vahan/
RUN /usr/sbin/update-ca-certificates
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends tzdata libicu72 libxml2 libxslt1.1 libldap-2.5-0 libssl3 \
        libgssapi-krb5-2 libpam0g libsystemd0 libzstd1 liblz4-1 libselinux1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=postgres /usr/lib/postgresql/17 /usr/lib/postgresql/17
# The official image moves postgresql.conf.sample to /usr/share/postgresql/ and leaves a relative symlink in 17/,
# so the whole directory is copied (copying only 17/ leaves the symlink dangling and initdb fails).
COPY --from=postgres /usr/share/postgresql /usr/share/postgresql
COPY --from=postgres /usr/lib/x86_64-linux-gnu/libpq.so.5* /usr/lib/x86_64-linux-gnu/
# Fail the build, not the run, if the copied PostgreSQL misses a shared library.
RUN ! { ldd /usr/lib/postgresql/17/bin/postgres /usr/lib/postgresql/17/bin/pg_ctl /usr/lib/postgresql/17/bin/initdb /usr/lib/postgresql/17/bin/createdb | grep 'not found'; }
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
COPY docker/qc-sut-entrypoint.sh /usr/local/bin/qc-sut-entrypoint
RUN sed -i 's/\x0d$//' /usr/local/bin/qc-sut-entrypoint && chmod 0755 /usr/local/bin/qc-sut-entrypoint
USER vahan
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/qc-sut-entrypoint"]
