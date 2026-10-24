# Nginx da borda: serve o front (build do Vite) e encaminha as rotas da API para o Django.
# Contexto de build: a raiz do repositório (precisa de frontend/ e nginx/).

FROM node:24.21.0-alpine AS front
WORKDIR /front
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=front /front/dist /usr/share/nginx/html
