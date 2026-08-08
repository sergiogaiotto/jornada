"""Aceite K06 (§10.2, onda 7) · A tela do DPO para de afirmar efeito inexistente.

`decisao_automatizada` governa em runtime **1 das 7** ações do vocabulário
(`ACOES_FIADAS = {jornada.ajustar}`), mas a tela e os efeitos diziam "A IA APLICA
sozinha — não há revisão humana antes do efeito" para QUALQUER ação marcada. Publicar
`otimizacao.propor` recebia 201, a tela confirmava a automação, e nada mudava — há um
aceite cujo único propósito é provar esse nada. É a plataforma afirmando efeito
inexistente exatamente na tela em que o DPO governa, sobre o artigo da LGPD (Art. 20)
em que a distinção "quem aplicou" é o ponto inteiro.

A fatia B (esta): parar de mentir, com o dado descendo do servidor.

- o vocabulário serve `acoes_com_enforcement`, DERIVADO de `ACOES_FIADAS` — a tela não
  redigita nomes de ação (padrão dos limites de PII: redigitado no React, envelhece na
  primeira fiação);
- os efeitos ganham TRÊS estados — fiada / marcada-e-inerte / não marcada — e o resumo
  conta só as fiadas;
- o 201 da publicação AVISA na hora quando uma autorização marcada não tem consumidor.

A fatia A (auto-aplicar `otimizacao.propor`) fica DE FORA por decisão: automatizar a
aprovação da top-1 é comportamento novo de produto, que exige emenda prévia (o gate A0
do plano da onda) — construí-lo só para encolher a lista de inertes seria a forma
sofisticada de teatro. Fica declarada aberta, com o aceite da inércia intacto.
"""

import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from application.services import portao_ia
from application.services.ia_responsavel_service import efeitos_em_portugues
from domain.ia_responsavel.politica import ACOES_VIA_AI
from tests.acceptance.test_F03_ia_responsavel_enforcement import _conservador, _h

RAIZ = Path(__file__).resolve().parents[3]
TSX = RAIZ / "frontend" / "src" / "pages" / "IaResponsavel.tsx"

ACAO_FIADA = next(iter(portao_ia.ACOES_FIADAS))
ACAO_INERTE = next(iter(set(ACOES_VIA_AI) - portao_ia.ACOES_FIADAS))


def _bloco_decisao(efeitos: list[dict[str, Any]]) -> dict[str, Any]:
    return next(b for b in efeitos if b["parametro"] == "decisao_automatizada")


def test_K06_vocabulario_serve_quais_acoes_tem_enforcement(client: TestClient) -> None:
    """A fonte única da tela: derivada das constantes, servida pela rota real."""
    vigente = client.get("/api/v1/ia-responsavel/politica", headers=_h("dev-dpo"))
    assert vigente.status_code == 200, vigente.text
    vocabulario = vigente.json()["vocabulario"]
    assert vocabulario["acoes_com_enforcement"] == sorted(portao_ia.ACOES_FIADAS)
    # e o vocabulário completo continua lá — o novo campo é aditivo
    assert set(vocabulario["acoes_via_ai"]) == set(ACOES_VIA_AI)


def test_K06_efeitos_distinguem_acao_fiada_de_inerte() -> None:
    """O estado do meio existe — e é o que separa verdade de overclaim.

    Inversão: colapsar `_efeito_da_acao` de volta a dois estados (marcada = "APLICA
    sozinha") derruba este teste na ação inerte.
    """
    conteudo = {"decisao_automatizada": {"pode_aplicar_sozinho": [ACAO_FIADA, ACAO_INERTE]}}
    itens = {i["chave"]: i for i in _bloco_decisao(efeitos_em_portugues(conteudo))["itens"]}

    assert "APLICA sozinha" in itens[ACAO_FIADA]["efeito"]
    assert "sem consumidor" in itens[ACAO_INERTE]["efeito"], (
        f"ação inerte marcada recebeu a frase da fiada: {itens[ACAO_INERTE]['efeito']!r}"
    )
    assert "APLICA sozinha" not in itens[ACAO_INERTE]["efeito"]
    # não marcada segue com a frase de sempre
    desmarcada = _bloco_decisao(efeitos_em_portugues({}))["itens"]
    assert all("PROPÕE" in i["efeito"] for i in desmarcada)


def test_K06_resumo_conta_so_as_fiadas() -> None:
    """ "6 de 7 ações são aplicadas pela IA" com 5 inertes era o resumo mentindo.

    Inversão: voltar o resumo a `len(automatizaveis)` derruba este teste.
    """
    todas = {"decisao_automatizada": {"pode_aplicar_sozinho": list(ACOES_VIA_AI)}}
    resumo = _bloco_decisao(efeitos_em_portugues(todas))["resumo"]
    assert f"{len(portao_ia.ACOES_FIADAS)} de {len(ACOES_VIA_AI)}" in resumo, resumo
    assert f"{len(ACOES_VIA_AI)} de {len(ACOES_VIA_AI)}" not in resumo, (
        f"o resumo contou as marcadas, não as fiadas: {resumo!r}"
    )
    assert "SEM consumidor" in resumo  # e a parte inerte é dita, não omitida

    # só a fiada marcada: nenhuma menção a autorização inerte
    so_fiada = {"decisao_automatizada": {"pode_aplicar_sozinho": [ACAO_FIADA]}}
    assert "SEM consumidor" not in _bloco_decisao(efeitos_em_portugues(so_fiada))["resumo"]


def test_K06_publicar_autorizacao_inerte_avisa_no_201(client: TestClient) -> None:
    """Quem publica descobre NA HORA — não num relatório seis meses depois.

    A publicação é aceita (a ação é do vocabulário; recusar quebraria a compatibilidade
    retroativa), mas o corpo do 201 nomeia cada autorização sem consumidor.

    Inversão: remover o bloco de avisos do `publicar` derruba este teste.
    """
    conteudo = _conservador(client)
    conteudo["decisao_automatizada"]["pode_aplicar_sozinho"] = [ACAO_INERTE]
    resposta = client.post(
        "/api/v1/ia-responsavel/politicas",
        json={"conteudo": conteudo, "motivo": "aceite K06 — autorização inerte avisa"},
        headers=_h("dev-dpo"),
    )
    assert resposta.status_code == 201, resposta.text
    avisos = resposta.json().get("avisos")
    assert avisos and any(ACAO_INERTE in a and "consumidor" in a for a in avisos), (
        f"o 201 não avisou que {ACAO_INERTE!r} é autorização sem efeito — veio {avisos!r}"
    )

    # publicar SÓ a fiada: zero avisos (o aviso não pode virar ruído permanente)
    conteudo["decisao_automatizada"]["pode_aplicar_sozinho"] = [ACAO_FIADA]
    limpa = client.post(
        "/api/v1/ia-responsavel/politicas",
        json={"conteudo": conteudo, "motivo": "aceite K06 — fiada não gera aviso"},
        headers=_h("dev-dpo"),
    )
    assert limpa.status_code == 201 and limpa.json().get("avisos") == [], limpa.text


def test_K06_a_tela_nao_redigita_quais_acoes_tem_enforcement() -> None:
    """O React lê `acoes_com_enforcement`; nenhum nome de ação vive no .tsx.

    Mesma doutrina dos limites de PII (a tela desenha o que o servidor sabe): um nome
    de ação hardcoded no componente envelhece na primeira fiação e a tela volta a
    mentir — na direção que for. Grep, declarado como tal: prova ausência de literal,
    não comportamento; quem prova comportamento são os testes acima.
    """
    texto = TSX.read_text(encoding="utf-8")
    assert "acoes_com_enforcement" in texto, (
        "a tela não consome o campo novo — o rótulo volta a depender só do checkbox"
    )
    for acao in ACOES_VIA_AI:
        assert acao not in texto, (
            f"o nome de ação {acao!r} está redigitado no IaResponsavel.tsx — "
            "o rótulo tem de descer do vocabulário"
        )
    # e o estado do meio aparece para o usuário
    assert re.search(r"sem consumidor|SEM consumidor", texto), (
        "a tela não tem o estado do meio — marcada-e-inerte voltaria a parecer fiada"
    )
