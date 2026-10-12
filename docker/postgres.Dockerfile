# Rebuild the upstream privilege-switch helper with a patched Go toolchain.
# The database engine, entrypoint and data layout stay on PostgreSQL 17.
FROM docker.io/library/golang:1.27.2-bookworm@sha256:5cf287a799e6b94384bad13d16b14904c531f51ba65792237e122ce42b392f61 AS gosu-build
ENV GOTOOLCHAIN=local
RUN CGO_ENABLED=0 go install github.com/tianon/gosu@1.19

FROM docker.io/library/postgres:17.11-bookworm@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826
COPY --from=gosu-build /go/bin/gosu /usr/local/bin/gosu
RUN test "$(gosu nobody id -u)" = "65534" \
    && gosu --version
