# Builds the screens and serves them with nginx, which also forwards /api to the backend so the
# browser sees one origin (the session cookie needs that).
FROM node:22-alpine AS build
WORKDIR /srv/frontend
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /srv/frontend/dist /usr/share/nginx/html
EXPOSE 80
