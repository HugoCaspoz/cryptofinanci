FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 TABLE_LAYOUT_PATH=/data/table_layouts/platform_1920x1080.json CARD_PROFILE_ROOT=/data/card_profiles APP_AUTH_COOKIE_SECURE=true
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends nginx supervisor gettext-base tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/scripts/restore_session.py ./scripts/restore_session.py
COPY backend/table_layouts ./default_layouts
COPY --from=frontend /build/dist /srv/frontend
COPY infra/railway/nginx.conf.template /etc/zeros/nginx.conf.template
COPY infra/railway/supervisord.conf /etc/zeros/supervisord.conf
COPY infra/railway/start.sh /usr/local/bin/zeros-start
RUN useradd --create-home zeros && chmod +x /usr/local/bin/zeros-start
EXPOSE 8080
CMD ["/usr/local/bin/zeros-start"]
