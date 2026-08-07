# API Jornada — build context = raiz do monorepo (requirements.txt fica na raiz, §2.2)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# A imagem instala do LOCK, nunca da declaração (emenda F04). `requirements.txt` traz
# faixas `~=X.Y` que resolvem na data do build: dois `docker build` do MESMO commit
# produziam imagens com bibliotecas diferentes, e foi assim que o FastAPI pulou de 0.115
# para 0.141 sem ninguém pedir — cegando o aceite `E05_A7` (emenda F01). Com o lock, o
# commit determina a imagem.
#
# `requirements.txt` viaja junto para FORENSE, não para teste: com os dois arquivos
# dentro da imagem dá para responder "o que foi declarado" e "o que foi instalado" sem
# voltar ao repositório. O gate `tests/unit/test_F04_lock_dependencias.py` NÃO roda aqui
# — a imagem copia só `backend/`, então o teste enxerga `/` como raiz e não acha nenhum
# dos dois arquivos. Quem roda o gate é o CI (repositório inteiro no checkout).
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# DECLARA que este ambiente foi construído a partir do lock. É a marca que tira
# `test_ambiente_instalado_e_exatamente_o_do_lock` do skip: comparar arquivo com arquivo
# não prova ambiente, só a leitura do que foi de fato instalado prova. A marca viaja na
# imagem para que qualquer container derivado daqui (com o repositório montado) já rode
# o gate armado, sem ninguém ter de lembrar de exportar a variável. Um teste estático
# garante que esta linha não some — sem ele o gate viraria skip permanente e calado.
ENV JORNADA_DEPS_DO_LOCK=1

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
