FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY apps/web-ui/package*.json ./
RUN npm ci
COPY apps/web-ui/ ./
ARG VITE_API_URL=""
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build
FROM nginx:1.28-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
