"""Política v1 de SEED (§11.4 "políticas v1") — conteúdo no formato de
`policy_versao.conteudo` (§4.1): {frequency_cap, quiet_hours, blackout, holdout_min,
alcadas, retencao_dias, breakers, precedencia}.

`POLITICA_SEED` é SEMENTE e FALLBACK, **nunca fonte da verdade em runtime** (achado 8
do UAT #5): quem governa é a linha PUBLICADA de `policy_versao` (§4.1), lida pelo
`PublicacoesPort` e INJETADA nos serviços. Enquanto o constante era importado direto,
publicar política pela tela T16 não mudava comportamento nenhum — parametrização que
não muda comportamento é teatro auditável. Um guarda-corpo de CI
(`tests/unit/test_achado8_guarda_corpo_politica.py`) falha se `application/services/`
voltar a importar daqui — e também se uma ROTA montar `PublicacoesLocais()` na mão, que
foi o furo literal do achado. Os únicos consumidores legítimos são as SEEDS
(`adapters/*_seeds.py`, que materializam a v1 em `policy_versao`) e o FALLBACK do
adapter de publicações, para o banco vazio devolver exatamente os mesmos valores da seed.

`blackout` e `precedencia` seguem no conjunto fechado do §4.1 (validados, versionados)
sem NENHUM consumidor em runtime — auditado e registrado como escopo aberto, não como
esquecimento; ver a emenda do achado 8. NÃO são "exibidos na T16": esta docstring dizia
isso e era falso — a política do §4.1 não tem tela, publica-se por `POST /api/v1/policies`
(a T16 mostra o Ateliê; a tela do DPO é a da IA Responsável, §10.2, que é outra política).

Valores coerentes com o SDD: quiet hours 20:00–08:00 (§5.1), holdout default 10% (§4.1
`segmento.holdout_pct`), breaker de optout 0,6% (§8-M10-A1), 7 listas de supressão na
precedência (§4.1 `lista_supressao`). Com o M12 parte 2 este dicionário vira a linha
v1 PUBLICADA de `policy_versao` (seeds) — CRUD em api/v1/plataforma.py.

Policy-as-code (M12 parte 2, §8-M12): `validar_conteudo` valida o conjunto FECHADO de
campos do §4.1 (erros ACUMULADOS, padrão do parser §7.1) e `violacoes_contra_conteudo`
calcula, por CÓDIGO (compliance nunca é LLM §1.1.3), o que uma OS em voo — congelada
em versão antiga (§8-M4-A2) — violaria na política nova: holdout de segmento abaixo do
`holdout_min` novo e breakers congelados no armar (§4.1 `launch.breakers`) mais
FROUXOS que os novos (limites `*_max`: congelado > novo). Caps de frequência/quiet
hours não têm artefato congelado comparável no v1 — ficam fora do relatório
(documentado no CHANGELOG-SDD.md).
"""

from typing import Any

# Conjunto FECHADO de campos de `policy_versao.conteudo` (§4.1) — todos obrigatórios.
CAMPOS_CONTEUDO: tuple[str, ...] = (
    "frequency_cap",
    "quiet_hours",
    "blackout",
    "holdout_min",
    "alcadas",
    "retencao_dias",
    "breakers",
    "precedencia",
)


def validar_conteudo(conteudo: Any) -> list[str]:
    """Erros ACUMULADOS do conteúdo de política (§4.1) — lista vazia = válido."""
    if not isinstance(conteudo, dict) or not conteudo:
        return ["conteudo deve ser objeto não-vazio no formato §4.1 policy_versao"]
    erros: list[str] = []
    for campo in CAMPOS_CONTEUDO:
        if campo not in conteudo:
            erros.append(f"conteudo sem campo obrigatório {campo!r} (§4.1)")
    for campo in conteudo:
        if campo not in CAMPOS_CONTEUDO:
            erros.append(f"campo desconhecido {campo!r} — conjunto fechado §4.1: nada fora dele")
    if "holdout_min" in conteudo and not _numerico(conteudo["holdout_min"], 0, 100):
        erros.append("holdout_min deve ser numérico entre 0 e 100 (§4.1 segmento.holdout_pct)")
    if "retencao_dias" in conteudo and not _numerico(conteudo["retencao_dias"], 1, 36500):
        erros.append("retencao_dias deve ser inteiro positivo (purge §10.4)")
    breakers = conteudo.get("breakers")
    if "breakers" in conteudo and (
        not isinstance(breakers, dict)
        or not breakers
        or any(not _numerico(v, 0, None) for v in breakers.values())
    ):
        erros.append("breakers deve ser {limite: numérico ≥ 0} (§8-M10; ex.: optout_pct_max)")
    alcadas = conteudo.get("alcadas")
    if "alcadas" in conteudo and (
        not isinstance(alcadas, list)
        or not alcadas
        or any(not isinstance(f, dict) or "ate" not in f or "papel" not in f for f in alcadas)
    ):
        erros.append("alcadas deve ser lista de faixas {ate, papel} (§8-M8 enviar-alcada)")
    quiet = conteudo.get("quiet_hours")
    if "quiet_hours" in conteudo and (
        not isinstance(quiet, dict) or "inicio" not in quiet or "fim" not in quiet
    ):
        erros.append("quiet_hours deve ter {inicio, fim} (§5.1)")
    return erros


def violacoes_contra_conteudo(
    *,
    holdouts: list[dict[str, Any]],
    breakers_congelados: list[dict[str, Any]],
    conteudo: dict[str, Any],
) -> list[dict[str, Any]]:
    """Violações que os artefatos CONGELADOS de uma OS em voo teriam contra a política
    nova (relatório de policy drift §8-M12) — 100% código, nenhum LLM.

    `holdouts` = [{segmento_id, holdout_pct}] (§4.1 `segmento`);
    `breakers_congelados` = [{launch_id, breakers}] (launch NÃO terminal — os limites
    foram congelados da política da época no armar, §8-M10)."""
    violacoes: list[dict[str, Any]] = []
    holdout_min = float(conteudo.get("holdout_min") or 0)
    for h in holdouts:
        if float(h["holdout_pct"]) < holdout_min:
            violacoes.append(
                {
                    "regra": "holdout_min",
                    "segmento_id": h["segmento_id"],
                    "congelado": h["holdout_pct"],
                    "novo": holdout_min,
                }
            )
    novos = conteudo.get("breakers") or {}
    for b in breakers_congelados:
        for limite, novo in novos.items():
            congelado = (b.get("breakers") or {}).get(limite)
            if congelado is not None and float(congelado) > float(novo):
                violacoes.append(  # limite `*_max` congelado mais FROUXO que o novo
                    {
                        "regra": f"breakers.{limite}",
                        "launch_id": b["launch_id"],
                        "congelado": congelado,
                        "novo": novo,
                    }
                )
    return violacoes


def _numerico(valor: Any, minimo: float | None, maximo: float | None) -> bool:
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        return False
    return (minimo is None or valor >= minimo) and (maximo is None or valor <= maximo)


def faixa_alcada(custo: float, politica: dict[str, Any]) -> dict[str, Any] | None:
    """Faixa de alçada da política para o custo previsto (§8-M8: `enviar-alcada`).

    `alcadas` = [{ate, papel}] em faixas crescentes; retorna a PRIMEIRA faixa com
    custo ≤ `ate` (None quando o custo excede a maior — fora de alçada, 409).
    """
    faixas = sorted(politica.get("alcadas") or [], key=lambda f: float(f["ate"]))
    for faixa in faixas:
        if custo <= float(faixa["ate"]):
            return {"ate": faixa["ate"], "papel": faixa["papel"]}
    return None


POLITICA_SEED: dict[str, Any] = {
    "versao": 1,
    "estado": "publicada",
    "conteudo": {
        "frequency_cap": {"email": 4, "sms": 2, "push": 5, "whatsapp": 2, "janela_dias": 7},
        "quiet_hours": {"inicio": "20:00", "fim": "08:00"},
        "blackout": [],
        "holdout_min": 10.0,
        "alcadas": [{"ate": 100_000, "papel": "lider"}, {"ate": 1_000_000, "papel": "aprovador"}],
        "retencao_dias": 180,
        # Limites dos breakers da Torre de Lançamento (§8-M10; congelados em
        # `launch.breakers` no armar — §4.1). optout 0,6% = §8-M10-A1; erro de
        # entrega e burn-rate vs projetado completam o contrato do M10 (valores
        # v1 do seed — a política do tenant os governa via M12).
        "breakers": {
            "optout_pct_max": 0.6,
            "bounce_pct_max": 2.0,
            "erro_entrega_pct_max": 5.0,
            "burn_rate_max": 1.5,
        },
        "precedencia": [
            "blacklist",
            "fraude",
            "nao_perturbe",
            "optout",
            "procon",
            "inadimplente",
            "reprovado_credito",
        ],
    },
}
