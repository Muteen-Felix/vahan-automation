FROM node:22-bookworm-slim
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY apps/browser-runner/package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --omit=dev
RUN npx playwright install --with-deps chromium \
    && apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && chown -R node:node /ms-playwright /app
COPY --chown=node:node apps/browser-runner/ ./
USER node
EXPOSE 3001
CMD ["node", "runner.mjs"]
