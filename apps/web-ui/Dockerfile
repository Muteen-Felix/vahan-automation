FROM docker.io/library/node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS build
WORKDIR /app
COPY apps/web-ui/package*.json ./
RUN npm ci
COPY apps/web-ui/ ./
ARG VITE_API_URL=""
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build
FROM docker.io/library/nginx:1.30.5-alpine@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94
RUN apk upgrade --no-cache
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
# Declared build provenance (T29): supplied by the build, so `docker image inspect` shows the revision the image
# was declared to be built from. It is not proof of the image bytes (docs/release/pins.md).
ARG VCS_REF=unknown
ARG VERSION=unknown
LABEL org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.version=$VERSION
EXPOSE 80
