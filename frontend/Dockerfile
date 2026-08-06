# SPA Jornada — build estático + nginx servindo dist e proxy /api → api:8000
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# A22 · version-stamp: o SHA entra no bundle (Vite lê VITE_GIT_SHA) e aparece no
# rodapé do shell — dá para conferir a versão da SPA sem abrir o DevTools.
ARG GIT_SHA=dev
ENV VITE_GIT_SHA=${GIT_SHA}
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
