"""Aceites do módulo M4 · Validação campo-a-campo & War Room (SDD §8-M4) — IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker e SEM REDE: fonte de validação = adapter de fixtures
(mocks/seeds/fontes_validacao.json §11), Langfuse no-op (conftest §10.8). O M4 é 100%
determinístico — nenhuma rota do módulo invoca LLM (§1.1.3).
"""

import hashlib
import uuid
from io import BytesIO
from typing import Any

from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.publicacoes import TARIFARIO_VIGENTE_ID, PublicacoesLocais
from app.errors import PROBLEM_CONTENT_TYPE
from domain.esteira.modelos import ETAPAS
from domain.governanca.politicas import POLITICA_PUBLICADA
from tests.conftest import TENANT_ALHEIO

TENANT = "torre-movel"

# Campos com fonte nas fixtures (§11) validam `ok`; "canais" NÃO tem fonte → `falha`.
BRIEFING_COM_FONTE: dict[str, Any] = {
    "publico": {"valor": "Pós-pago sem 5G", "inferido": False},
    "verba": {"valor": 250_000.0, "inferido": False},
}


def _h(token: str = "dev-analista") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _criar_os_discutida(client: TestClient, briefing: dict[str, Any]) -> dict[str, Any]:
    """OS pronta para o GO (§8-M4: GO parte de `discutida` e leva a `criada`)."""
    resposta = client.post(
        "/api/v1/os",
        json={"nome": "Upgrade Pós-Pago 5G", "tshirt": "G", "briefing": briefing},
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    os_ = resposta.json()
    avanco = client.post(f"/api/v1/os/{os_['id']}/fase", json={"fase": "discutida"}, headers=_h())
    assert avanco.status_code == 200, avanco.text
    return os_


def _validar(client: TestClient, os_id: str, campo: str) -> dict[str, Any]:
    resposta = client.post(f"/api/v1/os/{os_id}/validacoes/{campo}", headers=_h())
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def test_M4_A1(client: TestClient, app: FastAPI) -> None:
    """A1: GO com campo não decidido OU pendência bloqueante → 409 problem+json
    LISTANDO pendências e campos não decididos; resolvido tudo, o GO passa."""
    briefing = dict(BRIEFING_COM_FONTE) | {"canais": {"valor": ["email", "sms"], "inferido": True}}
    os_ = _criar_os_discutida(client, briefing)

    # nada decidido → 409 com TODOS os campos do briefing, sem pendências
    bloqueado = client.post(f"/api/v1/os/{os_['id']}/go", headers=_h())
    assert bloqueado.status_code == 409, bloqueado.text
    assert bloqueado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    corpo = bloqueado.json()
    assert corpo["campos_nao_decididos"] == ["publico", "verba", "canais"]
    assert corpo["pendencias"] == []
    assert "campos não decididos" in corpo["detail"]

    # checagem automática contra fonte (contagem, schema, frescor) com evidência (§8-M4)
    validacao = _validar(client, os_["id"], "publico")
    assert validacao["veredito"] == "ok"
    assert [c["tipo"] for c in validacao["checagens"]] == ["contagem", "schema", "frescor"]
    assert all(c["ok"] for c in validacao["checagens"])
    assert validacao["evidencia"]["fonte"] == "hybris_base_clientes"
    assert validacao["evidencia"]["contagem"] == 847_312
    _validar(client, os_["id"], "verba")

    # "canais" não tem fonte configurada (fixtures §11) → veredito `falha` = não decidido
    sem_fonte = _validar(client, os_["id"], "canais")
    assert sem_fonte["veredito"] == "falha"
    ainda = client.post(f"/api/v1/os/{os_['id']}/go", headers=_h())
    assert ainda.status_code == 409
    assert ainda.json()["campos_nao_decididos"] == ["canais"]

    # tratamento consciente: pendência ANCORADA no campo (origem validacao:{campo})
    pendencia = client.post(
        f"/api/v1/os/{os_['id']}/validacoes/canais/pendencia",
        json={"severidade": "media"},
        headers=_h(),
    )
    assert pendencia.status_code == 201, pendencia.text
    aberta = pendencia.json()
    assert aberta["origem"] == "validacao:canais"
    assert aberta["bloqueante"] is True and aberta["status"] == "aberta"

    # pendência bloqueante aberta → GO segue 409, agora LISTANDO a pendência (A1)
    bloqueado2 = client.post(f"/api/v1/os/{os_['id']}/go", headers=_h())
    assert bloqueado2.status_code == 409
    corpo2 = bloqueado2.json()
    assert corpo2["campos_nao_decididos"] == ["canais"]
    assert corpo2["pendencias"] == [
        {"numero": aberta["numero"], "titulo": aberta["titulo"], "severidade": "media"}
    ]
    assert f"#{aberta['numero']}" in corpo2["detail"]
    # outbox: cada bloqueio do portão gera gate.blocked (§2.3)
    bloqueios = app.state.repositorio_os.listar_eventos(
        os_id=uuid.UUID(os_["id"]), tipo="gate.blocked"
    )
    assert len(bloqueios) == 3 and bloqueios[-1].payload["portao"] == "go"

    # âncoras inválidas → 404 (validação, pendência e thread do War Room)
    assert client.post(f"/api/v1/os/{os_['id']}/validacoes/cpf", headers=_h()).status_code == 404
    thread_404 = client.post(
        f"/api/v1/os/{os_['id']}/threads",
        json={"campo": "cpf", "mensagem": "âncora inválida"},
        headers=_h(),
    )
    assert thread_404.status_code == 404
    thread = client.post(
        f"/api/v1/os/{os_['id']}/threads",
        json={"campo": "canais", "mensagem": "Push entra no mix?", "titulo": "Mix de canais"},
        headers=_h(),
    )
    assert thread.status_code == 201 and thread.json()["campo"] == "canais"

    # RBAC (§8-M0): solicitante não valida nem executa GO
    assert (
        client.post(
            f"/api/v1/os/{os_['id']}/validacoes/publico", headers=_h("dev-solicitante")
        ).status_code
        == 403
    )
    go_negado = client.post(f"/api/v1/os/{os_['id']}/go", headers=_h("dev-solicitante"))
    assert go_negado.status_code == 403

    # pendência resolvida → campo decidido por tratamento consciente → GO passa
    resolvida = client.post(f"/api/v1/pendencias/{aberta['id']}/resolver", headers=_h())
    assert resolvida.status_code == 200, resolvida.text
    go = client.post(f"/api/v1/os/{os_['id']}/go", headers=_h())
    assert go.status_code == 200, go.text
    assert go.json()["os"]["fase"] == "criada"


def test_M4_A2(client: TestClient, app: FastAPI) -> None:
    """A2: após o GO, `os.frozen` contém as versões PUBLICADAS ATUAIS de agentes e
    política (§4.1: {agent_versions, policy_version, tarifario_id, slas}) e os SLAs
    ficam congelados como `sla_clock`s correndo."""
    os_ = _criar_os_discutida(client, dict(BRIEFING_COM_FONTE))
    for campo in BRIEFING_COM_FONTE:
        _validar(client, os_["id"], campo)
    go = client.post(f"/api/v1/os/{os_['id']}/go", headers=_h())
    assert go.status_code == 200, go.text
    frozen = go.json()["os"]["frozen"]

    # versões publicadas atuais dos agentes (fonte: SKILL.md publicados — CHANGELOG M4)
    assert frozen["agent_versions"] == PublicacoesLocais().versoes_agentes()
    assert set(frozen["agent_versions"]) >= {"consultor", "engineer", "visual", "copy", "content"}
    assert all(versao for versao in frozen["agent_versions"].values())
    # política publicada + tarifário vigente congelados junto (§4.1)
    assert frozen["policy_version"] == POLITICA_PUBLICADA["versao"]
    assert frozen["tarifario_id"] == TARIFARIO_VIGENTE_ID

    # SLAs congelados: uma entrada por etapa canônica da esteira, prazos cumulativos
    assert list(frozen["slas"]) == list(ETAPAS)
    prazos = [entrada["prazo"] for entrada in frozen["slas"].values()]
    assert prazos == sorted(prazos) and len(set(prazos)) == len(prazos)
    # e materializados como sla_clock correndo (§8-M1/§8-M4)
    clocks = app.state.repositorio_os.listar_sla_clocks(uuid.UUID(os_["id"]))
    assert sorted(c.etapa for c in clocks) == sorted(ETAPAS)
    assert all(c.estado == "correndo" for c in clocks)

    # frozen persistido na OS (GET /os/{id}) + eventos do portão (§2.3)
    consulta = client.get(f"/api/v1/os/{os_['id']}", headers=_h())
    assert consulta.json()["frozen"] == frozen
    eventos = app.state.repositorio_os.listar_eventos(os_id=uuid.UUID(os_["id"]))
    tipos = [e.type for e in eventos]
    assert "gate.passed" in tipos and "os.phase_changed" in tipos

    # GO não repete: fase já é `criada` → transição ilegal (409, mapa M1)
    assert client.post(f"/api/v1/os/{os_['id']}/go", headers=_h()).status_code == 409


def test_M4_A3(client: TestClient, app: FastAPI) -> None:
    """A3: doc executivo (.docx) gerado no GO e ARMAZENADO (`documento_portao` §4.1),
    com hash sha256 do conteúdo e metadados no corpo da resposta."""
    os_ = _criar_os_discutida(client, dict(BRIEFING_COM_FONTE))
    for campo in BRIEFING_COM_FONTE:
        _validar(client, os_["id"], campo)
    go = client.post(f"/api/v1/os/{os_['id']}/go", headers=_h())
    assert go.status_code == 200, go.text
    documento = go.json()["documento"]

    codigo = go.json()["os"]["codigo"]
    assert documento["nome_arquivo"] == f"{codigo}-portao-go.docx"
    assert documento["portao"] == "go" and documento["tamanho_bytes"] > 0
    assert len(documento["hash"]) == 64 and int(documento["hash"], 16) >= 0

    # armazenado em `documento_portao` (§8-M4-A3) — bytes de um .docx real (zip "PK")
    armazenados = app.state.repositorio_os.listar_documentos(uuid.UUID(os_["id"]), portao="go")
    assert [d.hash for d in armazenados] == [documento["hash"]]
    conteudo = armazenados[0].conteudo
    assert conteudo[:2] == b"PK" and len(conteudo) == documento["tamanho_bytes"]
    assert hashlib.sha256(conteudo).hexdigest() == documento["hash"]

    # conteúdo executivo: título com o código da OS + versões congeladas (python-docx §3.2)
    textos = [p.text for p in Document(BytesIO(conteudo)).paragraphs]
    assert any(f"Portão GO · {codigo}" in t for t in textos)
    assert any(t.startswith("Política: v") for t in textos)

    # evento de outbox com o hash do documento (§2.3)
    eventos = app.state.repositorio_os.listar_eventos(
        os_id=uuid.UUID(os_["id"]), tipo="documento_portao.gerado"
    )
    assert eventos and eventos[-1].payload["hash"] == documento["hash"]


def test_M4_A4(client: TestClient, tokens_outro_tenant: dict[str, str]) -> None:
    """A4 (emenda B01): o estado da validação é RECUPERÁVEL por leitura —
    `GET /os/{id}/validacoes` devolve a decisão vigente de cada campo (veredito,
    checagens, evidência, quem/quando) e `GET /os/{id}/pendencias` o que está aberto.
    Sem isso a tela T3 zerava a cada reload (UAT #2) embora o dado estivesse no banco."""
    briefing = dict(BRIEFING_COM_FONTE) | {"canais": {"valor": ["email"], "inferido": True}}
    os_ = _criar_os_discutida(client, briefing)

    # OS ainda sem checagem alguma: leituras existem e vêm vazias (não 404/405)
    assert client.get(f"/api/v1/os/{os_['id']}/validacoes", headers=_h()).json() == []
    assert client.get(f"/api/v1/os/{os_['id']}/pendencias", headers=_h()).json() == []

    _validar(client, os_["id"], "publico")
    _validar(client, os_["id"], "canais")  # sem fonte → falha
    pendencia = client.post(
        f"/api/v1/os/{os_['id']}/validacoes/canais/pendencia",
        json={"titulo": "Confirmar mix de canais", "severidade": "alta"},
        headers=_h(),
    )
    assert pendencia.status_code == 201, pendencia.text
    aberta = pendencia.json()

    # --- leitura das validações: uma linha por campo checado, com autoria ---
    lidas = client.get(f"/api/v1/os/{os_['id']}/validacoes", headers=_h())
    assert lidas.status_code == 200, lidas.text
    corpo = lidas.json()
    assert [(v["campo"], v["veredito"]) for v in corpo] == [("publico", "ok"), ("canais", "falha")]
    validado = corpo[0]
    assert [c["tipo"] for c in validado["checagens"]] == ["contagem", "schema", "frescor"]
    assert validado["evidencia"]["fonte"] == "hybris_base_clientes"
    assert validado["por"] == "analista@dev.jornada.local"  # quem
    assert validado["atualizado_em"] is not None  # quando
    # campo NUNCA checado não aparece na leitura (a tela sabe o que falta decidir)
    assert "verba" not in [v["campo"] for v in corpo]

    # --- leitura das pendências: numero, severidade, status, bloqueante, âncora ---
    pendencias = client.get(f"/api/v1/os/{os_['id']}/pendencias", headers=_h())
    assert pendencias.status_code == 200, pendencias.text
    listadas = pendencias.json()
    assert [p["numero"] for p in listadas] == [aberta["numero"]]
    assert listadas[0]["severidade"] == "alta" and listadas[0]["status"] == "aberta"
    assert listadas[0]["bloqueante"] is True
    assert listadas[0]["origem"] == "validacao:canais"  # âncora no campo (A1)

    # resolver não some da lista — muda de status (a tela distingue aberta de tratada)
    assert (
        client.post(f"/api/v1/pendencias/{aberta['id']}/resolver", headers=_h()).status_code == 200
    )
    tratada = client.get(f"/api/v1/os/{os_['id']}/pendencias", headers=_h()).json()
    assert [p["status"] for p in tratada] == ["resolvida"]

    # leituras são de qualquer autenticado (§8-M0) e escopadas por tenant
    assert (
        client.get(f"/api/v1/os/{os_['id']}/validacoes", headers=_h("dev-solicitante")).status_code
        == 200
    )
    # achado 5/UAT5: id vazado + usuário de outro tenant → 404 (não vaza existência);
    # X-Tenant forjado com credencial daqui não passa do middleware → 403.
    alheio = {
        "X-Tenant": TENANT_ALHEIO,
        "Authorization": f"Bearer {tokens_outro_tenant['pleno']}",
    }
    assert client.get(f"/api/v1/os/{os_['id']}/validacoes", headers=alheio).status_code == 404
    assert client.get(f"/api/v1/os/{os_['id']}/pendencias", headers=alheio).status_code == 404
    forjado = {"X-Tenant": "outro", "Authorization": "Bearer dev-analista"}
    assert client.get(f"/api/v1/os/{os_['id']}/validacoes", headers=forjado).status_code == 403


def test_M4_A5(client: TestClient, app: FastAPI) -> None:
    """A5 (emenda B01): revalidar o MESMO campo é idempotente — atualiza a decisão
    vigente (mesmo `id`, `created_at` preservado) em vez de empilhar duplicata. O
    histórico de execuções continua no outbox `validacao.executada` (§2.3)."""
    os_ = _criar_os_discutida(client, dict(BRIEFING_COM_FONTE))

    primeira = _validar(client, os_["id"], "publico")
    segunda = _validar(client, os_["id"], "publico")
    terceira = _validar(client, os_["id"], "publico")

    # mesma linha: id estável e created_at da PRIMEIRA checagem
    assert segunda["id"] == primeira["id"] == terceira["id"]
    assert terceira["created_at"] == primeira["created_at"]
    assert terceira["atualizado_em"] >= primeira["atualizado_em"]

    # a leitura (e o repositório) enxergam UMA validação do campo, não três
    lidas = client.get(f"/api/v1/os/{os_['id']}/validacoes", headers=_h()).json()
    assert [v["campo"] for v in lidas] == ["publico"]
    assert lidas[0]["id"] == primeira["id"]
    persistidas = app.state.repositorio_os.listar_validacoes(uuid.UUID(os_["id"]), "publico")
    assert len(persistidas) == 1

    # cada execução segue auditável no outbox — 3 eventos, a revalidação marcada
    eventos = app.state.repositorio_os.listar_eventos(
        os_id=uuid.UUID(os_["id"]), tipo="validacao.executada"
    )
    assert [e.payload["revalidacao"] for e in eventos] == [False, True, True]
    assert all(e.payload["validacao_id"] == primeira["id"] for e in eventos)

    # e a idempotência não afrouxa o portão: o outro campo continua não decidido (A1)
    bloqueado = client.post(f"/api/v1/os/{os_['id']}/go", headers=_h())
    assert bloqueado.status_code == 409
    assert bloqueado.json()["campos_nao_decididos"] == ["verba"]
