FROM docker.io/library/node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392
COPY docker/certs/ /usr/local/share/ca-certificates/vahan/
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && /usr/sbin/update-ca-certificates
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
WORKDIR /app
COPY apps/browser-runner/package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --omit=dev
RUN npx playwright install --with-deps chromium \
    && apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libnss3-tools \
    && rm -rf /var/lib/apt/lists/* \
    && for certificate in /usr/local/share/ca-certificates/vahan/*.crt; do \
         [ -f "$certificate" ] || continue; \
         if [ ! -d /home/node/.pki/nssdb ]; then \
           mkdir -p /home/node/.pki/nssdb; \
           certutil -N --empty-password -d sql:/home/node/.pki/nssdb; \
         fi; \
         certutil -A -d sql:/home/node/.pki/nssdb -n "$(basename "$certificate")" -t "C,," -i "$certificate"; \
       done \
    && if [ -d /home/node/.pki ]; then chown -R node:node /home/node/.pki; fi \
    && chown -R node:node /ms-playwright /app
COPY --chown=node:node apps/browser-runner/ ./
# The running worker uses node directly; npm/npx are build tools only.
RUN rm -rf /usr/local/lib/node_modules/npm /opt/yarn* \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/yarn /usr/local/bin/yarnpkg
# Declared build provenance (T29): supplied by the build, so `docker image inspect` shows the revision the image
# was declared to be built from. It is not proof of the image bytes (docs/release/pins.md).
ARG VCS_REF=unknown
ARG VERSION=unknown
LABEL org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.version=$VERSION
USER node
EXPOSE 3001
CMD ["node", "runner.mjs"]
