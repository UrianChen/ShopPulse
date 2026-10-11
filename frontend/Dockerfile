FROM node:24.14.0-alpine AS builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
COPY LICENSE /usr/share/doc/shoppulse/LICENSE
COPY licenses/ /usr/share/doc/shoppulse/licenses/
EXPOSE 8080
