"""Aceites do achado 5 (UAT5) — `X-Tenant` é ASSERÇÃO do cliente, não fonte da verdade.

O portador autenticado JÁ carrega o escopo (`Usuario.tenant_id`, §8-M0). Em `/api/v1/*`
o tenant EFETIVO passa a vir dele; o header continua obrigatório (contrato §8 intacto)
mas é CONFERIDO — divergiu do portador, 403 problem+json antes de qualquer rota. É a
mesma regra que o C03 já adotou para o link mágico, agora aplicada ao resto da API.

Achado 22 (mesmo eixo): a sequência de código da OS e a checagem de duplicidade eram
GLOBAIS — o número da OS contava o volume de TODOS os clientes e `POST /os` com código
alheio devolvia 409, um oráculo de existência. Passam a ser por tenant.

Rodam via TestClient, sem docker (repositório em memória — §1.3.5).
"""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import PORTAL_TOKENS
from app.errors import PROBLEM_CONTENT_TYPE
from app.main import ROTAS_PUBLICAS
from tests.conftest import TENANT_ALHEIO as OUTRO_TENANT

TENANT = "torre-movel"


def _h(token: str = "dev-analista", tenant: str = TENANT) -> dict[str, str]:
    return {"X-Tenant": tenant, "Authorization": f"Bearer {token}"}


def _os_payload(codigo: str | None = None) -> dict[str, Any]:
    corpo: dict[str, Any] = {"nome": "Campanha 5G", "tshirt": "M", "briefing": {}}
    if codigo is not None:
        corpo["codigo"] = codigo
    return corpo


# O segundo tenant REAL vem da fixture `tokens_outro_tenant` (tests/conftest.py):
# desde que o header é conferido contra o portador, provar isolamento exige um USUÁRIO
# do outro tenant — forjar header é o que o fix proíbe.


# ------------------------------------------------------------------ Achado 5 (E05)
def test_E05_A1_header_divergente_do_portador_recusado(client: TestClient) -> None:
    """Token de `torre-movel` anunciando outro tenant → 403 problem+json, na LEITURA e
    na ESCRITA (na VPS isso devolvia 200/201 e criava OS em tenant inventado)."""
    leitura = client.get("/api/v1/os", headers=_h(tenant="tenant-invasor"))
    assert leitura.status_code == 403, leitura.text
    assert leitura.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "X-Tenant" in leitura.json()["detail"]

    escrita = client.post("/api/v1/os", json=_os_payload(), headers=_h(tenant="tenant-invasor"))
    assert escrita.status_code == 403, escrita.text

    # e nada foi criado do lado de cá
    minhas = client.get("/api/v1/os", headers=_h())
    assert minhas.status_code == 200 and minhas.json() == []


def test_E05_A2_portal_confere_igual(client: TestClient) -> None:
    """O token de PORTAL (§8-M3) também carrega tenant — mesma conferência."""
    resposta = client.post(
        "/api/v1/pedidos",
        json={"solicitante": {"nome": "Beto"}, "conteudo": {}},
        headers=_h("portal-dev", tenant=OUTRO_TENANT),
    )
    assert resposta.status_code == 403, resposta.text
    assert PORTAL_TOKENS["portal-dev"].tenant_id == TENANT  # o escopo real do portador


def test_E05_A3_header_conferido_libera_o_proprio_tenant(client: TestClient) -> None:
    """Compatibilidade: header IGUAL ao do portador segue o fluxo normal (§8)."""
    criada = client.post("/api/v1/os", json=_os_payload(), headers=_h())
    assert criada.status_code == 201, criada.text
    assert criada.json()["tenant_id"] == TENANT


def test_E05_A4_sem_header_segue_400_e_credencial_invalida_segue_401(
    client: TestClient,
) -> None:
    """O contrato §8 não muda: sem header, 400 (não 403). Credencial não reconhecida
    não vira 403 — a rota responde 401, sem revelar se o tenant existe."""
    sem_header = client.get("/api/v1/os", headers={"Authorization": "Bearer dev-analista"})
    assert sem_header.status_code == 400

    token_falso = client.get(
        "/api/v1/os",
        headers={"X-Tenant": "tenant-invasor", "Authorization": "Bearer nao-existe"},
    )
    assert token_falso.status_code == 401


def test_E05_A5_rotas_publicas_do_link_magico_intactas(client: TestClient) -> None:
    """C03 preservado: `/aprovacao/*` segue SEM header e SEM Bearer (o aprovador
    externo não tem como mandar nenhum dos dois) — 404 do token inexistente, nunca
    400/403 do middleware. Header anunciado segue sendo anúncio conferido no serviço."""
    sem_nada = client.get("/api/v1/aprovacao/token-que-nao-existe")
    assert sem_nada.status_code == 404

    anunciando = client.get(
        "/api/v1/aprovacao/token-que-nao-existe", headers={"X-Tenant": "torre-residencial"}
    )
    assert anunciando.status_code == 404


# ------------------------------------------------- Achado 5 · a CLASSE, não o caso
_ROTAS_DE_LEITURA = [
    "/api/v1/os",
    "/api/v1/pedidos",
    "/api/v1/policies",
    "/api/v1/policies/drift",
    "/api/v1/atelie/agentes",
    "/api/v1/auditoria",
]


@pytest.mark.parametrize("rota", _ROTAS_DE_LEITURA)
def test_E05_A6_header_forjado_e_recusado_em_todo_o_prefixo(client: TestClient, rota: str) -> None:
    """A conferência é do MIDDLEWARE, não de uma rota: vale para todo `/api/v1/*`.

    Todos os routers do §8 derivam o tenant da mesma dependência (`os_governanca.
    get_tenant` → `request.state.tenant_id`), então basta o header não ser mais a
    fonte para a classe inteira fechar — este aceite fixa isso."""
    resposta = client.get(rota, headers=_h(tenant="tenant-invasor"))
    assert resposta.status_code == 403, f"{rota} → {resposta.status_code}: {resposta.text[:200]}"


def test_E05_A7_nenhuma_rota_privada_mora_sob_o_prefixo_publico(app: FastAPI) -> None:
    """A isenção do C03 é um `startswith` — o que ela cobre precisa ficar FECHADO.

    Com barra no fim (`/api/v1/aprovacao/`), `/api/v1/aprovacaoX` não entra; e o único
    conteúdo do prefixo são as duas rotas do link mágico. Se alguém pendurar rota nova
    aí, este aceite quebra ANTES de virar um bypass silencioso de tenant."""
    # Varre o CONTRATO (paths do OpenAPI), não `app.routes`: a partir do FastAPI 0.12x
    # o `include_router` deixa de achatar as rotas em `app.routes`, e a varredura ingênua
    # devolvia lista VAZIA — um aceite de segurança que passa por não enxergar nada é
    # pior que aceite nenhum. O `~=` do requirements permitia 0.115 no dev e 0.141 no CI,
    # então o teste passava aqui e quebrava lá (emenda F01).
    publicas = sorted(
        caminho for caminho in app.openapi()["paths"] if caminho.startswith(ROTAS_PUBLICAS)
    )
    assert publicas == ["/api/v1/aprovacao/{token}", "/api/v1/aprovacao/{token}/decidir"], publicas
    assert all(prefixo.endswith("/") for prefixo in ROTAS_PUBLICAS), ROTAS_PUBLICAS


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer  dev-analista",  # dois espaços
        "bearer dev-analista",  # esquema minúsculo
        "BEARER dev-analista",
        "Bearer\tdev-analista",  # tab no lugar do espaço
        "Bearer dev-analista extra",  # lixo depois do token
        "Basic ZGV2LWFuYWxpc3RhOg==",  # outro esquema
    ],
)
def test_E05_A8_parsing_do_authorization_nao_abre_brecha(
    client: TestClient, authorization: str
) -> None:
    """A brecha estrutural do desenho: o middleware e a rota lêem o MESMO header por
    caminhos diferentes (`usuario_do_authorization` × `HTTPBearer`). Se um reconhece o
    portador e o outro não, a variante que o middleware NÃO reconhece passa com o
    header forjado — e a rota, que reconhece, atende no tenant inventado.

    Nenhuma destas variantes pode virar 200: ou o middleware recusa (403), ou a rota
    recusa (401). Nunca as duas serem permissivas ao mesmo tempo."""
    resposta = client.get(
        "/api/v1/os", headers={"X-Tenant": "tenant-invasor", "Authorization": authorization}
    )
    assert resposta.status_code in (401, 403), (
        f"{authorization!r} → {resposta.status_code}: {resposta.text[:200]}"
    )


def test_E05_A9_id_vazado_nao_atravessa_o_tenant_em_nenhum_router(
    client: TestClient, tokens_outro_tenant: dict[str, str]
) -> None:
    """O outro vetor: credencial LEGÍTIMA do vizinho + id vazado daqui → 404 em todos
    os routers por-recurso (o header agora bate com o portador, então o request entra
    — quem barra é o escopo de tenant via OS, §4.1)."""
    criada = client.post("/api/v1/os", json=_os_payload(), headers=_h())
    assert criada.status_code == 201, criada.text
    os_id = criada.json()["id"]
    jornada = client.post(f"/api/v1/os/{os_id}/jornada", json={}, headers=_h())
    assert jornada.status_code == 201, jornada.text
    jornada_id = jornada.json()["jornada"]["id"]

    alheio = _h(tokens_outro_tenant["pleno"], tenant=OUTRO_TENANT)
    for rota in (
        f"/api/v1/os/{os_id}",
        f"/api/v1/os/{os_id}/pendencias",
        f"/api/v1/os/{os_id}/jornada",
        f"/api/v1/os/{os_id}/jornadas",
        f"/api/v1/jornadas/{jornada_id}",
        f"/api/v1/jornadas/{jornada_id}/export?formato=json",
    ):
        resposta = client.get(rota, headers=alheio)
        assert resposta.status_code == 404, f"{rota} → {resposta.status_code}"

    assert client.get("/api/v1/os", headers=alheio).json() == []


# ----------------------------------------------------------------- Achado 22 (E22)
def test_E22_A1_codigo_de_os_e_unico_por_tenant(
    client: TestClient, tokens_outro_tenant: dict[str, str]
) -> None:
    """Dois tenants podem ter o MESMO código de OS. Antes, `POST /os` com o código de
    outro cliente devolvia 409 "Já existe OS com código ..." — oráculo de existência
    que permitia enumerar a plataforma a partir de um tenant vazio."""
    minha = client.post("/api/v1/os", json=_os_payload("OS-2026-0457"), headers=_h())
    assert minha.status_code == 201, minha.text

    alheia = client.post(
        "/api/v1/os",
        json=_os_payload("OS-2026-0457"),
        headers=_h(tokens_outro_tenant["pleno"], tenant=OUTRO_TENANT),
    )
    assert alheia.status_code == 201, alheia.text
    assert alheia.json()["tenant_id"] == OUTRO_TENANT

    # duplicidade DENTRO do tenant continua barrada (§8-M1)
    repetida = client.post("/api/v1/os", json=_os_payload("OS-2026-0457"), headers=_h())
    assert repetida.status_code == 409, repetida.text


def test_E22_A2_numeracao_de_um_tenant_nao_enxerga_a_do_outro(
    client: TestClient, tokens_outro_tenant: dict[str, str]
) -> None:
    """O sequencial `OS-{ano}-NNNN` é POR TENANT: o número da OS não conta mais o
    volume de todos os clientes (vazamento de negócio)."""
    primeira = client.post("/api/v1/os", json=_os_payload(), headers=_h())
    segunda = client.post("/api/v1/os", json=_os_payload(), headers=_h())
    assert [primeira.status_code, segunda.status_code] == [201, 201]
    codigos = [primeira.json()["codigo"], segunda.json()["codigo"]]
    assert codigos[0].endswith("-0001") and codigos[1].endswith("-0002")

    do_outro = client.post(
        "/api/v1/os",
        json=_os_payload(),
        headers=_h(tokens_outro_tenant["pleno"], tenant=OUTRO_TENANT),
    )
    assert do_outro.status_code == 201, do_outro.text
    assert do_outro.json()["codigo"] == codigos[0]  # começa do 1, não do 3
