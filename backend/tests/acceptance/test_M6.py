"""Aceites do módulo M6 · Criativo T6 (SDD §8-M6) — IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker e SEM REDE: LLM = adapter fake (`app.state.llm` —
§1.3.5; pipeline visual→copy→content em 120b + warn de compliance em 20b), Langfuse
no-op (§10.8). Os VALIDADORES são código puro (domain/criativo/validadores.py — zero
LLM): A1 exercita-os também como unit.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.llm.fake import LLMFake
from app.auth import DEV_TOKENS
from app.errors import PROBLEM_CONTENT_TYPE
from domain.criativo import matriz, validadores
from domain.criativo.erros import AprovacaoRequerHumano
from domain.criativo.modelos import CelulaCriativo, Criativo

TENANT = "torre-movel"

KV_MASTER: dict[str, Any] = {
    "conceito": "Upgrade 5G sem surpresa na fatura",
    "promessa": "Mais velocidade no plano que você já tem",
}

SMS_160 = "x" * 160
SMS_161 = "x" * 161


def _h(token: str = "dev-analista") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _celula(canal: str, variante: str, mensagem: str, **extras: Any) -> dict[str, Any]:
    return {"canal": canal, "variante": variante, "conteudo": {"mensagem": mensagem, **extras}}


def _matriz_json(celulas: list[dict[str, Any]]) -> str:
    """Saída enlatada do CONTENT no contrato do SKILL.md (§7.1/§8-M6)."""
    return json.dumps(
        {
            "celulas": celulas,
            "evidencias": ["criativos: KV master aprovado na campanha 5G de maio (histórico T6)"],
            "resposta": "Matriz canal×variante montada a partir do KV master.",
        },
        ensure_ascii=False,
    )


CELULAS_CONFORMES: list[dict[str, Any]] = [
    _celula("email", "A", "Seu plano com 5G liberado.", assunto="5G liberado", cta="Ativar"),
    _celula("email", "B", "Velocidade nova, fatura igual.", assunto="Sem surpresa", cta="Ativar"),
    _celula("sms", "A", SMS_160),
    _celula("sms", "B", "Ative o 5G no seu plano sem mudar de fatura. Responda SIM."),
]


def _fake(celulas: list[dict[str, Any]], avisos: list[str] | None = None) -> LLMFake:
    """120b (visual/copy/content) devolve a matriz; 20b devolve o warn de linguagem."""
    return LLMFake(
        respostas_por_perfil={
            "120b": _matriz_json(celulas),
            "20b": json.dumps({"avisos": avisos or []}, ensure_ascii=False),
        }
    )


def _criar_os(client: TestClient) -> dict[str, Any]:
    resposta = client.post(
        "/api/v1/os",
        json={"nome": "Upgrade Pós-Pago 5G", "tshirt": "G", "briefing": {"objetivo": "upsell"}},
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _gerar(
    client: TestClient, app: FastAPI, celulas: list[dict[str, Any]], avisos: list[str] | None = None
) -> tuple[Any, dict[str, Any]]:
    app.state.llm = _fake(celulas, avisos)
    os_ = _criar_os(client)
    resposta = client.post(
        f"/api/v1/os/{os_['id']}/criativos/gerar",
        json={"kv_master": KV_MASTER, "canais": ["email", "sms"], "variantes": ["A", "B"]},
        headers=_h(),
    )
    return resposta, os_


def test_M6_A1(client: TestClient, app: FastAPI) -> None:
    """A1: SMS 161 chars → 422 (validador DETERMINÍSTICO — código, nunca LLM §1.1.3);
    160 passa. Unit dos validadores + caminho API completo."""
    # --- unit: veredito por código ---
    assert validadores.problemas_da_celula("sms", "A", {"mensagem": SMS_160}) == []
    problemas = validadores.problemas_da_celula("sms", "A", {"mensagem": SMS_161})
    assert problemas and "161" in problemas[0] and "160" in problemas[0]
    assert validadores.problemas_da_celula(
        "whatsapp", "A", {"mensagem": "oi", "template": {"nome": "promo", "status": "pendente"}}
    )
    assert (
        validadores.problemas_da_celula(
            "whatsapp", "A", {"mensagem": "oi", "template": {"nome": "promo", "status": "aprovado"}}
        )
        == []
    )
    assert validadores.problemas_do_kv_master({"headline": "Plano 100% GRÁTIS"})  # termo proibido

    # --- API: matriz do agente com SMS de 161 chars → 422 problem+json, nada persiste ---
    reprovado, os_ = _gerar(client, app, [_celula("sms", "A", SMS_161)])
    assert reprovado.status_code == 422, reprovado.text
    assert reprovado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    corpo = reprovado.json()
    assert any("161" in p and "sms/A" in p for p in corpo["problemas"])
    assert app.state.repositorio_os.listar_criativos(uuid.UUID(os_["id"])) == []

    # --- matriz conforme → 201; warn LLM só ACRESCENTA avisos (não bloqueia) ---
    aviso = "Urgência artificial no CTA do sms/B."
    criado, _ = _gerar(client, app, CELULAS_CONFORMES, avisos=[aviso])
    assert criado.status_code == 201, criado.text
    corpo = criado.json()
    assert corpo["via_ai"] is True
    assert corpo["avisos"] == [aviso]
    assert len(corpo["invocacao_ids"]) == 3  # pipeline visual→copy→content (§7.2)
    assert {(c["canal"], c["variante"]) for c in corpo["criativo"]["celulas"]} == {
        ("email", "A"),
        ("email", "B"),
        ("sms", "A"),
        ("sms", "B"),
    }
    # roster §7.2: especialistas em 120b (3 chamadas) + warn de compliance em 20b
    assert [c["perfil"] for c in app.state.llm.chamadas] == ["120b", "120b", "120b", "20b"]


def test_M6_A2(client: TestClient, app: FastAPI) -> None:
    """A2: edição do KV master marca TODAS as células derivadas `adaptado_revisar`
    (aprovações caem — novo olhar humano); KV com termo proibido → 422 sem efeito."""
    criado, _ = _gerar(client, app, CELULAS_CONFORMES)
    assert criado.status_code == 201, criado.text
    criativo = criado.json()["criativo"]

    # analista aprova uma célula antes da edição do KV
    aprovada = client.patch(
        f"/api/v1/criativos/{criativo['id']}/celula",
        json={"canal": "email", "variante": "A", "acao": "aprovar"},
        headers=_h(),
    )
    assert aprovada.status_code == 200, aprovada.text
    estados = {(c["canal"], c["variante"]): c["estado"] for c in aprovada.json()["celulas"]}
    assert estados[("email", "A")] == "aprovado"

    # compliance determinístico também vale na edição: termo proibido → 422, nada muda
    reprovado = client.put(
        f"/api/v1/criativos/{criativo['id']}/kv-master",
        json={"kv_master": {"conceito": "Plano 100% grátis para sempre"}},
        headers=_h(),
    )
    assert reprovado.status_code == 422
    assert any("termo proibido" in p for p in reprovado.json()["problemas"])
    intacto = app.state.repositorio_os.obter_criativo(uuid.UUID(criativo["id"]))
    assert matriz.obter_celula(intacto, "email", "A").estado == "aprovado"

    # edição válida → TODAS as células `adaptado_revisar`; aprovação cai (A2)
    editado = client.put(
        f"/api/v1/criativos/{criativo['id']}/kv-master",
        json={"kv_master": dict(KV_MASTER) | {"promessa": "5G no plano atual, sem reajuste"}},
        headers=_h(),
    )
    assert editado.status_code == 200, editado.text
    celulas = editado.json()["criativo"]["celulas"]
    assert len(celulas) == 4
    assert all(c["estado"] == "adaptado_revisar" for c in celulas)
    assert all(c["aprovada_por"] is None and c["aprovada_em"] is None for c in celulas)

    # §10.6: a edição NUNCA depende de LLM — hub fora, PUT segue 200 (warn vazio)
    app.state.llm = LLMFake(disponivel=False)
    degradado = client.put(
        f"/api/v1/criativos/{criativo['id']}/kv-master",
        json={"kv_master": dict(KV_MASTER)},
        headers=_h(),
    )
    assert degradado.status_code == 200, degradado.text
    assert degradado.json()["avisos"] == []
    # evento de outbox da edição (§2.3)
    eventos = app.state.repositorio_os.listar_eventos(tipo="criativo.kv_master_editado")
    assert eventos and len(eventos[-1].payload["celulas_marcadas"]) == 4


def test_M6_A3(client: TestClient, app: FastAPI) -> None:
    """A3: nenhuma célula vai a `aprovado` via agente — só usuário com papel analista+
    (regra pura no domínio + RBAC na rota); toda célula NASCE `gerado`."""
    # --- unit: agente (por=None) jamais aprova ---
    criativo_puro = Criativo(
        id=uuid.uuid4(),
        os_id=uuid.uuid4(),
        kv_master=dict(KV_MASTER),
        celulas=[CelulaCriativo(canal="email", variante="A", conteudo={"mensagem": "olá"})],
    )
    with pytest.raises(AprovacaoRequerHumano):
        matriz.aprovar_celula(criativo_puro, "email", "A", por=None, agora=datetime.now(UTC))

    # --- API: mesmo que o LLM proponha "estado": "aprovado", toda célula nasce `gerado` ---
    celulas_maliciosas = [dict(c, estado="aprovado") for c in CELULAS_CONFORMES]
    criado, _ = _gerar(client, app, celulas_maliciosas)
    assert criado.status_code == 201, criado.text
    criativo = criado.json()["criativo"]
    assert all(c["estado"] == "gerado" for c in criativo["celulas"])
    assert all(c["aprovada_por"] is None for c in criativo["celulas"])

    # solicitante (sem papel analista+) não aprova → 403 RBAC (§8-M0)
    payload = {"canal": "email", "variante": "A", "acao": "aprovar"}
    negado = client.patch(
        f"/api/v1/criativos/{criativo['id']}/celula", json=payload, headers=_h("dev-solicitante")
    )
    assert negado.status_code == 403
    assert negado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    # analista aprova → registro {aprovada_por, aprovada_em} do HUMANO (§4.1)
    analista = DEV_TOKENS["dev-analista"]
    aprovada = client.patch(
        f"/api/v1/criativos/{criativo['id']}/celula", json=payload, headers=_h()
    )
    assert aprovada.status_code == 200, aprovada.text
    celula = next(
        c for c in aprovada.json()["celulas"] if (c["canal"], c["variante"]) == ("email", "A")
    )
    assert celula["estado"] == "aprovado"
    assert celula["aprovada_por"] == str(analista.id) and celula["aprovada_em"] is not None

    # re-aprovação → 409 (EstadoInvalido, mapa M1); célula fora da matriz → 404
    assert (
        client.patch(
            f"/api/v1/criativos/{criativo['id']}/celula", json=payload, headers=_h()
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/v1/criativos/{criativo['id']}/celula",
            json={"canal": "whatsapp", "variante": "A", "acao": "aprovar"},
            headers=_h(),
        ).status_code
        == 404
    )

    # devolver para revisão é livre ao analista; aprovação anterior cai
    revisar = client.patch(
        f"/api/v1/criativos/{criativo['id']}/celula",
        json={"canal": "email", "variante": "A", "acao": "revisar", "observacao": "Ajustar CTA"},
        headers=_h(),
    )
    assert revisar.status_code == 200
    celula = next(
        c for c in revisar.json()["celulas"] if (c["canal"], c["variante"]) == ("email", "A")
    )
    assert celula["estado"] == "revisar" and celula["aprovada_por"] is None
