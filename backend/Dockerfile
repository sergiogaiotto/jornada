# API Jornada — build context = raiz do monorepo (requirements.txt fica na raiz, §2.2)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
# Fixtures de fontes/read-model usadas em runtime (validação campo-a-campo, recontagem
# de audiência): o código resolve <raiz>/mocks/seeds — na imagem, isso é /mocks/seeds.
COPY mocks/seeds/ /mocks/seeds/

# A22 · version-stamp: o commit viaja DENTRO da imagem e sai em GET /healthz.sha —
# é o que permite ao smoke pós-deploy provar que o que subiu é o que foi buildado.
ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA}

EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
