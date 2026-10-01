# syntax=docker/dockerfile:1
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY portal/package.json portal/package-lock.json ./portal/
RUN npm ci && npm ci --prefix portal
COPY . ./
ARG VITE_API_URL=
ARG PUBLIC_SITE_URL=
ARG PUBLIC_INDEXING=false
ENV VITE_API_URL=$VITE_API_URL PUBLIC_SITE_URL=$PUBLIC_SITE_URL PUBLIC_INDEXING=$PUBLIC_INDEXING
RUN npm run build

FROM nginx:1.28-alpine
ENV BACKEND_URL=http://backend:8010 TRUSTED_PROXY_CIDR=127.0.0.1/32 \
    NGINX_ENVSUBST_FILTER="^(BACKEND_URL|TRUSTED_PROXY_CIDR)$"
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=755 nginx/10-validate-env.sh /docker-entrypoint.d/10-validate-env.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/health
CMD ["nginx", "-g", "daemon off;"]
