FROM golang:1.27.2-bookworm AS tools
RUN GOBIN=/out CGO_ENABLED=0 go install github.com/tianon/gosu@1.19 \
    && GOBIN=/out CGO_ENABLED=0 go install filippo.io/age/cmd/age@v1.3.2
FROM postgres:17-bookworm
RUN apt-get update && apt-get upgrade -y && apt-get install -y python3 \
    && rm -rf /var/lib/apt/lists/* && useradd --uid 10003 backup-agent \
    && mkdir /data && chown backup-agent:backup-agent /data
WORKDIR /service
COPY --from=tools /out/gosu /usr/local/bin/gosu
COPY --from=tools /out/age /usr/local/bin/age
COPY docker/backup/daemon.py ./daemon.py
USER backup-agent
ENTRYPOINT ["python3", "-u", "/service/daemon.py"]
