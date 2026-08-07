"""O argon2 sai do event loop (frente 1) — medido, não afirmado.

O bug: `POST /auth/login` era `async def` e chamava, no corpo, um argon2id de 64 MiB × 3
passes (~100 ms de CPU, zero I/O). Corpo `async` roda DENTRO do event loop, e o event
loop é um só — então esses 100 ms não atrasavam o login: atrasavam TUDO. N logins
concorrentes serializavam o servidor inteiro por N × 100 ms, `/healthz` incluído. E como
`/auth/login` é a única rota que hasheia SEM autenticação, o congelamento estava à venda
para qualquer um, ao preço de um POST.

Como se mede
------------
Um BATIMENTO: uma corrotina que faz `await asyncio.sleep(0.01)` num laço e anota a
lacuna real entre um tique e o outro. Enquanto o loop está livre, as lacunas ficam na
casa dos 10 ms. Quando alguém bloqueia o loop, o batimento simplesmente PARA — e a maior
lacuna registrada é, ao milissegundo, quanto tempo o servidor ficou cego.

`test_a_mecanica_*` prova a mecânica em dois apps mínimos (um `def`, um `async def`) com
a mesma carga de argon2: é a comparação controlada, o "antes e depois".
`test_o_login_real_*` aponta o mesmo medidor para a rota de verdade — é ele que quebra
se alguém reescrever `def login` como `async def login` (a inversão verificada).

Marcado `unit` e sem rede: o transporte é ASGI em memória (`httpx.ASGITransport`).
"""

from __future__ import annotations

import asyncio
import time

import httpx
from fastapi import FastAPI

from adapters.relogio import RelogioSistema
from app.middleware_limite import LimitePorIp
from domain.identidade import senha as regras_senha
from tests.conftest import ClienteJornada

TENANT = {"X-Tenant": "torre-movel"}
ADMIN = TENANT | {"Authorization": "Bearer dev-admin"}
PROVISORIA = "provisoria-longa-01"
# N do aceite: 20 logins concorrentes na rota real.
CONCORRENTES = 20
# N da comparação controlada: menor de propósito. Com `def`, os N hashes rodam DE FATO em
# paralelo no threadpool e disputam os poucos núcleos do container do gate — acima de ~10
# a disputa por CPU passa a dominar a medida e esconde o efeito que se quer isolar (loop
# bloqueado × loop livre). O aceite de verdade é o `test_o_login_real_*`.
CONCORRENTES_MECANICA = 10
TIQUE_S = 0.01


async def maior_lacuna_do_batimento(
    aplicacao: FastAPI, caminho: str, corpo: dict, cabecalhos: dict, quantos: int
) -> tuple[float, list[int]]:
    """Dispara `quantos` requests concorrentes e devolve (maior lacuna do batimento, status)."""
    lacunas: list[float] = []
    parar = asyncio.Event()

    async def batimento() -> None:
        ultimo = time.perf_counter()
        while not parar.is_set():
            await asyncio.sleep(TIQUE_S)
            agora = time.perf_counter()
            lacunas.append(agora - ultimo)
            ultimo = agora

    tarefa = asyncio.create_task(batimento())
    await asyncio.sleep(0.05)  # deixa o batimento pegar ritmo antes da carga
    transporte = httpx.ASGITransport(app=aplicacao)
    async with httpx.AsyncClient(transport=transporte, base_url="http://medicao") as cliente:
        respostas = await asyncio.gather(
            *(cliente.post(caminho, json=corpo, headers=cabecalhos) for _ in range(quantos))
        )
    parar.set()
    await tarefa
    return max(lacunas), [r.status_code for r in respostas]


def app_de_carga(*, assincrono: bool) -> FastAPI:
    """App mínimo cuja única rota paga um argon2 — a diferença é só `def` vs `async def`."""
    aplicacao = FastAPI()

    if assincrono:

        @aplicacao.post("/carga")
        async def carga_async() -> dict[str, bool]:  # o bug, reproduzido
            regras_senha.consumir_tempo_de_verificacao()
            return {"ok": True}

    else:

        @aplicacao.post("/carga")
        def carga_sync() -> dict[str, bool]:  # o conserto: FastAPI joga no threadpool
            regras_senha.consumir_tempo_de_verificacao()
            return {"ok": True}

    return aplicacao


async def test_a_mecanica_async_def_cega_o_loop_e_def_nao() -> None:
    """A comparação controlada. Mesmo trabalho, mesma concorrência, só muda a assinatura.

    A asserção é RELATIVA (o sync tem de ficar numa fração do async) porque o número
    absoluto depende da máquina; o que não depende de máquina é a natureza do problema:
    no loop, os N hashes acontecem em fila indiana e o loop não roda nada nesse tempo.
    """
    lacuna_async, status_async = await maior_lacuna_do_batimento(
        app_de_carga(assincrono=True), "/carga", {}, {}, CONCORRENTES_MECANICA
    )
    lacuna_sync, status_sync = await maior_lacuna_do_batimento(
        app_de_carga(assincrono=False), "/carga", {}, {}, CONCORRENTES_MECANICA
    )
    print(  # o número medido É o entregável deste teste
        f"\n[argon2 × {CONCORRENTES_MECANICA} concorrentes] maior lacuna do batimento — "
        f"async def: {lacuna_async * 1000:.0f} ms | def: {lacuna_sync * 1000:.0f} ms"
    )
    assert set(status_async) == {200} and set(status_sync) == {200}
    assert lacuna_async > 0.2, "o loop deveria ter travado com N hashes em async def"
    assert lacuna_sync < lacuna_async / 2, (
        f"o threadpool deveria manter o loop respirando: {lacuna_sync:.3f}s vs {lacuna_async:.3f}s"
    )


async def test_o_login_real_nao_cega_o_event_loop(app: FastAPI) -> None:
    """A rota DE VERDADE, sob 20 logins concorrentes, mantém o loop atendendo.

    INVERSÃO: trocar `def login` por `async def login` em `api/v1/autenticacao.py` faz
    esta asserção falhar — é o que amarra o teste ao conserto, e não a um app de mentira.

    O limitador do app é substituído por um de teto alto: aqui se mede o event loop, não
    o rate limit (10 logins simultâneos do mesmo IP encostariam no `TETO_CUSTO`).
    """
    app.state.limite_login = LimitePorIp(RelogioSistema(), teto_custo=10_000, teto_falhas=10_000)
    # `ClienteJornada` e não `TestClient` cru: o preparo cria a conta com `Bearer
    # dev-admin`, token que não existe em `APP_ENV=prod` (§10.3). O cliente materializa
    # o portador declarado como sessão real, então este aceite vale nos dois ambientes.
    with ClienteJornada(app) as preparacao:
        criada = preparacao.post(
            "/api/v1/auth/usuarios",
            json={
                "email": "medida@torre.local",
                "nome": "Medida",
                "papeis": ["analista"],
                "senha_provisoria": PROVISORIA,
            },
            headers=ADMIN,
        )
        assert criada.status_code == 201, criada.text

    lacuna, status = await maior_lacuna_do_batimento(
        app,
        "/api/v1/auth/login",
        {"email": "medida@torre.local", "senha": PROVISORIA},
        TENANT,
        CONCORRENTES,
    )
    print(
        f"\n[POST /auth/login × {CONCORRENTES} concorrentes] maior lacuna do batimento: "
        f"{lacuna * 1000:.0f} ms"
    )
    assert set(status) == {200}
    assert lacuna < 0.3, (
        f"o event loop ficou cego por {lacuna:.3f}s durante {CONCORRENTES} logins — "
        "as rotas que hasheiam voltaram a ser `async def`?"
    )
