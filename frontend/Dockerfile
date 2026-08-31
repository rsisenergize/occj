# Deployment target: Railway, as its own service (Railway has no first-class
# "static site" product like Vercel -- a Dockerfile-built nginx service is
# the standard way to host a static SPA there). Also used for local
# docker-compose parity.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Baked into the JS bundle at build time (Vite env vars aren't readable at
# container runtime) -- set this as a build-time variable on the Railway
# service to the backend service's public URL.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx-templates/default.conf.template /etc/nginx/templates/default.conf.template
# Railway injects $PORT at runtime; nginx:alpine's entrypoint envsubst's
# *.template files in /etc/nginx/templates using only variables that are
# actually set in the environment, so nginx's own $uri etc. are left alone.
# The default here just makes `docker run` work without Railway involved.
ENV PORT=8080
EXPOSE 8080
