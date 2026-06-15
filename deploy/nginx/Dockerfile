ARG NODE_IMAGE=node:20-alpine

FROM ${NODE_IMAGE} AS frontend-build

WORKDIR /app

ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY miniapp-frontend/package*.json /app/
RUN npm ci

COPY miniapp-frontend /app
RUN npm run build

FROM nginx:1.27-alpine

COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /app/dist /usr/share/nginx/html
