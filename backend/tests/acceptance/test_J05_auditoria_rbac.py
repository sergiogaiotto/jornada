"""J05 (auditoria da onda 6) — o conteúdo do ledger na trilha respeita o Art. 20.

O painel de auditoria da T16 (J05) é o PRIMEIRO consumidor de GET /auditoria, e a
auditoria cética pegou o vazamento: a lista embutia input/output/judge COMPLETOS de
toda invocação a QUALQUER papel autenticado, enquanto `POST /auditoria/reconstruir`
barra o MESMO conteúdo a dpo|lider. Agora a lista redige o conteúdo para quem não pode
reconstruir; as métricas operacionais (tokens/latência/agente) — o que a T16 mostra —
seguem para todos.

INVERSÃO: remover o `incluir_conteudo=pode_ver_conteudo` da rota (voltar a incluir
sempre) deixa `test_J05_analista_nao_ve_o_conteudo_do_ledger` vermelho.
"""

from typing import Any

from fastapi import FastAPI
from starlette.testclient import TestClient

from tests.acceptance.test_M12 import _invocacao_via_consultor

TENANT = "torre-movel"
MENSAGEM = "Qual verba você sugere para o upgrade 5G?"


def _h(token: str) -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _detalhe_via_ai(client: TestClient, token: str) -> dict[str, Any]:
    trilha = client.get(
        "/api/v1/auditoria",
        params={"tipo": "agent.invoked", "agente": "consultor"},
        headers=_h(token),
    )
    assert trilha.status_code == 200, trilha.text
    eventos = [e for e in trilha.json()["eventos"] if e.get("invocacao")]
    assert eventos, f"deveria haver evento via_ai com detalhe para {token}"
    return eventos[-1]["invocacao"]


def test_J05_analista_nao_ve_o_conteudo_do_ledger(client: TestClient, app: FastAPI) -> None:
    _invocacao_via_consultor(client, app)  # gera a linha real do ledger (fluxo M3)
    det = _detalhe_via_ai(client, "dev-analista")
    # métricas operacionais SEGUEM (é o que a T16 mostra)
    assert det["agente"] == "consultor" and det["tokens"] is not None
    # conteúdo do Art. 20 REDIGIDO — o prompt do usuário não vaza pela lista
    assert isinstance(det["input"], str) and "restrito" in det["input"].lower()
    assert isinstance(det["output"], str) and "restrito" in det["output"].lower()
    assert MENSAGEM not in str(det["input"])


def test_J05_dpo_e_lider_veem_o_conteudo_como_no_reconstruir(
    client: TestClient, app: FastAPI
) -> None:
    _invocacao_via_consultor(client, app)
    for token in ("dev-dpo", "dev-lider"):
        det = _detalhe_via_ai(client, token)
        assert isinstance(det["input"], dict), token
        assert det["input"].get("mensagem") == MENSAGEM, token
