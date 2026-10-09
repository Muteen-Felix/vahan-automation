FROM python:3.12-slim-trixie
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10002 soc && mkdir /data && chown soc:soc /data
WORKDIR /service
COPY docker/soc/collector.py ./collector.py
USER soc
EXPOSE 3100
CMD ["python", "-u", "collector.py"]
