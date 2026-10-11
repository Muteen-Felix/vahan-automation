# Rebuild the upstream privilege-switch helper with a patched Go toolchain.
# The database engine, entrypoint and data layout stay on PostgreSQL 17.
FROM golang:1.27.2-bookworm AS gosu-build
ENV GOTOOLCHAIN=local
RUN CGO_ENABLED=0 go install github.com/tianon/gosu@1.19

FROM postgres:17.11-bookworm
COPY --from=gosu-build /go/bin/gosu /usr/local/bin/gosu
RUN test "$(gosu nobody id -u)" = "65534" \
    && gosu --version
