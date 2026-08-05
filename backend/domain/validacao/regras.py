"""Regras da validação campo-a-campo (T3) e do portão GO (T4) — SDD §8-M4.

Tudo determinístico (§1.1.3): checagem contra fonte = contagem, schema, frescor;
"campo decidido" e o portão GO são funções puras sobre validações + pendências.
O congelamento de SLAs materializa `sla_clock`s (prazos cumulativos pela ordem
canônica da esteira §4.1) e o bloco `frozen.slas` (§4.1: congelado no GO).
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from domain.campanha.fases import pendencias_bloqueando
from domain.campanha.modelos import Pendencia, SlaClock
from domain.esteira.modelos import ETAPAS
from domain.validacao.erros import GoBloqueado
from domain.validacao.modelos import ValidacaoCampo

# SLA default (dias) por etapa da esteira quando a OS não definiu o seu no workflow
# (etapa_workflow.sla_dias §4.1). Valores de implementação — ver CHANGELOG-SDD.md (M4).
SLA_DIAS_PADRAO: dict[str, int] = {
    "briefing": 2,
    "discovery": 3,
    "audiencia": 3,
    "criativos": 5,
    "configuracao": 3,
    "disparo": 1,
    "acompanhamento": 15,
}
assert set(SLA_DIAS_PADRAO) == set(ETAPAS)  # contrato: uma entrada por etapa canônica

FASE_POS_GO = "criada"  # §8-M4: GO → fase criada


def origem_do_campo(campo: str) -> str:
    """`pendencia.origem` que ancora a pendência ao campo (POST .../{campo}/pendencia)."""
    return f"validacao:{campo}"


def executar_checagens(
    valor: Any, fonte: dict[str, Any] | None, agora: datetime
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Checagem automática do campo contra a fonte (§8-M4): contagem, schema, frescor.

    `fonte` vem das fixtures de fonte (§11, mocks/seeds/fontes_validacao.json):
    {fonte, contagem, schema: [{campo, tipo}], atualizado_ha_horas, sla_frescor_horas}.
    Devolve (veredito, checagens, evidencia); sem fonte configurada → falha.
    """
    if fonte is None:
        checagens = [
            {
                "tipo": "fonte",
                "ok": False,
                "detalhe": "Nenhuma fonte configurada para o campo (fixtures §11).",
            }
        ]
        evidencia = {"fonte": None, "consultado_em": agora.isoformat()}
        return "falha", checagens, evidencia

    contagem = int(fonte.get("contagem", 0))
    schema = list(fonte.get("schema") or [])
    schema_ok = bool(schema) and all(
        isinstance(coluna, dict) and coluna.get("campo") and coluna.get("tipo") for coluna in schema
    )
    atualizado_ha_horas = float(fonte.get("atualizado_ha_horas", 0.0))
    sla_frescor_horas = float(fonte.get("sla_frescor_horas", 24.0))
    ultima_atualizacao = agora - timedelta(hours=atualizado_ha_horas)

    checagens = [
        {
            "tipo": "contagem",
            "ok": contagem > 0,
            "detalhe": f"{contagem} registros na fonte {fonte.get('fonte')!r}.",
        },
        {
            "tipo": "schema",
            "ok": schema_ok,
            "detalhe": f"{len(schema)} colunas declaradas (todas com campo+tipo: {schema_ok}).",
        },
        {
            "tipo": "frescor",
            "ok": atualizado_ha_horas <= sla_frescor_horas,
            "detalhe": (
                f"Atualizada há {atualizado_ha_horas:g}h (SLA de frescor: {sla_frescor_horas:g}h)."
            ),
        },
    ]
    veredito = "ok" if all(c["ok"] for c in checagens) else "falha"
    evidencia = {
        "fonte": fonte.get("fonte"),
        "valor_validado": valor,
        "contagem": contagem,
        "schema": schema,
        "ultima_atualizacao": ultima_atualizacao.isoformat(),
        "sla_frescor_horas": sla_frescor_horas,
        "consultado_em": agora.isoformat(),
    }
    return veredito, checagens, evidencia


def campo_decidido(
    campo: str, validacoes: list[ValidacaoCampo], pendencias: list[Pendencia]
) -> bool:
    """Campo decidido ⇔ última validação com veredito `ok` OU tratamento consciente:
    existe pendência ancorada no campo e nenhuma delas segue aberta (resolvida/aceita)."""
    do_campo = [v for v in validacoes if v.campo == campo]
    if do_campo and do_campo[-1].veredito == "ok":
        return True
    tratativas = [p for p in pendencias if p.origem == origem_do_campo(campo)]
    return bool(tratativas) and all(p.status != "aberta" for p in tratativas)


def validar_portao_go(
    briefing: dict[str, Any],
    validacoes: list[ValidacaoCampo],
    pendencias: list[Pendencia],
) -> None:
    """Portão do GO (A1): campo não decidido OU pendência bloqueante aberta → GoBloqueado
    (409) listando ambos. A ordem de `campos_nao_decididos` segue a do briefing."""
    nao_decididos = [
        campo for campo in briefing if not campo_decidido(campo, validacoes, pendencias)
    ]
    bloqueando = pendencias_bloqueando(pendencias, FASE_POS_GO)
    if not nao_decididos and not bloqueando:
        return
    partes: list[str] = []
    if nao_decididos:
        partes.append(f"campos não decididos: {', '.join(nao_decididos)}")
    if bloqueando:
        resumo = "; ".join(f"#{p.numero} {p.titulo}" for p in bloqueando)
        partes.append(f"pendências bloqueantes abertas: {resumo}")
    raise GoBloqueado(f"GO bloqueado (§8-M4-A1) — {' · '.join(partes)}.", nao_decididos, bloqueando)


def congelar_slas(
    os_id: uuid.UUID, etapas_workflow: list[Any], agora: datetime
) -> tuple[dict[str, Any], list[SlaClock]]:
    """Congela os SLAs no GO (§8-M1/§8-M4): um `sla_clock` correndo por etapa canônica,
    com prazos CUMULATIVOS na ordem da esteira; devolve (frozen.slas, clocks).

    `sla_dias` da etapa do workflow (quando definido) prevalece sobre o default.
    """
    sla_por_etapa = {
        e.nome: e.sla_dias for e in etapas_workflow if getattr(e, "sla_dias", None) is not None
    }
    prazo_acumulado = agora
    slas: dict[str, Any] = {}
    clocks: list[SlaClock] = []
    for nome in ETAPAS:
        dias = sla_por_etapa.get(nome, SLA_DIAS_PADRAO[nome])
        prazo_acumulado = prazo_acumulado + timedelta(days=dias)
        slas[nome] = {"sla_dias": dias, "prazo": prazo_acumulado.isoformat()}
        clocks.append(
            SlaClock(
                id=uuid.uuid4(),
                os_id=os_id,
                etapa=nome,
                prazo=prazo_acumulado,
                estado="correndo",
                pausas=[],
            )
        )
    return slas, clocks
