# Contexto de build = ./mocks (compose) — o mock lê as seeds compartilhadas (§11.2).
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir "fastapi~=0.115" "uvicorn[standard]~=0.30"
WORKDIR /app
COPY datacloud-server/main.py ./
COPY seeds/datacloud_segmentos.json ./seeds/
EXPOSE 8081
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081"]
