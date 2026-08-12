FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine AS runner
COPY --from=builder /app/dist /usr/share/nginx/html
# nginx:alpine runs envsubst on /etc/nginx/templates/*.template at startup,
# substituting ${BACKEND_URL} from the environment. Default targets the
# docker-compose `app` service; ECS overrides it with the Cloud Map DNS name.
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV BACKEND_URL=http://app:8000
# Only substitute BACKEND_URL — leave nginx's own $host/$uri/$remote_addr alone.
ENV NGINX_ENVSUBST_FILTER=BACKEND_URL
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
