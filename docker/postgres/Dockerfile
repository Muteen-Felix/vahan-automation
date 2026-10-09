FROM golang:1.27.2-bookworm AS tools
RUN GOBIN=/out CGO_ENABLED=0 go install github.com/tianon/gosu@1.19
FROM postgres:17-bookworm
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
COPY --from=tools /out/gosu /usr/local/bin/gosu
