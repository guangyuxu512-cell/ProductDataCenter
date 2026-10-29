FROM node:22-alpine AS build
WORKDIR /app
RUN npm install -g pnpm@11.25.0
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY frontend/package.json ./frontend/package.json
RUN pnpm install --frozen-lockfile
COPY frontend ./frontend
RUN pnpm --dir frontend build

FROM nginx:1.28-alpine
COPY --from=build /app/frontend/dist /usr/share/nginx/html
COPY deploy/nginx.conf.template /etc/product-workbench/nginx.conf.template
COPY deploy/40-product-workbench.sh /docker-entrypoint.d/40-product-workbench.sh
RUN chmod +x /docker-entrypoint.d/40-product-workbench.sh
