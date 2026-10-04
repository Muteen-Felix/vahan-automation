FROM mcr.microsoft.com/playwright:v1.63.0-noble
WORKDIR /app
USER root
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
COPY --chown=pwuser:pwuser apps/browser-runner/package*.json ./
RUN npm ci --omit=dev
COPY --chown=pwuser:pwuser apps/browser-runner/ ./
USER pwuser
EXPOSE 3001
CMD ["node", "runner.mjs"]
