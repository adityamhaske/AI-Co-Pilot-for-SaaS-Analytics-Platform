# Build the static bundle, then serve it from nginx. The previous image ran `vite dev`,
# which is a development server: single-threaded, unminified, and not meant to face
# traffic.
FROM node:22-slim AS builder

WORKDIR /app

# `npm ci` installs exactly the lockfile, which `npm install` does not guarantee.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# VITE_* values are inlined at build time, so the API URL is a build argument rather
# than a runtime environment variable.
ARG VITE_API_BASE_URL=http://localhost:6001
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build


FROM nginx:1.27-alpine AS runtime

# nginx:alpine already ships an unprivileged `nginx` user; run as it rather than root.
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Writable paths for a non-root nginx.
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx \
    && touch /var/run/nginx.pid \
    && chown nginx:nginx /var/run/nginx.pid

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
