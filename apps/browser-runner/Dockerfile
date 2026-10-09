FROM node:22-bookworm-slim
COPY docker/certs/ /usr/local/share/ca-certificates/vahan/
RUN apt-get update \
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
USER node
EXPOSE 3001
CMD ["node", "runner.mjs"]
