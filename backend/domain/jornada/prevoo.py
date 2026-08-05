"""Pré-voo (T11) — bateria pass/warn/fail com evidência (SDD §8-M9), parte PURA.

CÓDIGO PURO, zero I/O e **LLM PROIBIDO neste caminho** (§5.4/§10.6): cada checagem
devolve `{item, status: pass|warn|fail, evidencia}`; o serviço (prevoo_service) fornece
os insumos atrás de portas (SFMC, read model, repositório) e agrega o semáforo:

- `checar_opt_in(grafo)` — todo `channel.*` com opt-in configurado (§5.3).
- `checar_frescor_hybris(frescor)` — ciclo D-1 do Hybris (§8-M5-A4): ≤24h pass,
  ≤48h warn (um ciclo perdido), >48h fail.
- `lint_ampscript(texto)` / `checar_lint_ampscript(conteudos)` — lint SIMPLES e
  determinístico: delimitadores `%%[ ]%%` e `%%= =%%` balanceados.
- `checar_limites_sfmc(recursos)` — limites do SFMC verificáveis por código
  (LIMITES_SFMC): tamanho de chave/nome, activities por journey, campos por DE.
- `semaforo(itens)` — fail ⇒ vermelho · warn ⇒ amarelo · senão verde. FAIL bloqueia
  apply; apply em prod exige pré-voo executado e não-vermelho (§5.4.4).
"""

from typing import Any

# Limites SFMC verificáveis por código (v1 — ver CHANGELOG-SDD.md M9 fatia 2):
# chave (CustomerKey/eventDefinitionKey) ≤ 36; nome ≤ 128; ≤ 200 activities por
# journey; ≤ 500 campos por Data Extension.
LIMITES_SFMC: dict[str, int] = {
    "chave_max": 36,
    "nome_max": 128,
    "activities_max": 200,
    "campos_de_max": 500,
}

# Frescor Hybris (fixtures §11: ciclo D-1 = 24h — §8-M5-A4)
FRESCOR_HYBRIS_PASS_H = 24.0
FRESCOR_HYBRIS_WARN_H = 48.0

_CANAIS_JGC = ("channel.email", "channel.sms", "channel.push", "channel.whatsapp", "channel.rcs")


def item(nome: str, status: str, evidencia: dict[str, Any]) -> dict[str, Any]:
    """Forma canônica de um item da bateria (§8-M9): pass/warn/fail com evidência."""
    return {"item": nome, "status": status, "evidencia": evidencia}


def semaforo(itens: list[dict[str, Any]]) -> str:
    """Agrega a bateria: qualquer fail ⇒ vermelho; qualquer warn ⇒ amarelo; senão verde."""
    status = {i["status"] for i in itens}
    if "fail" in status:
        return "vermelho"
    return "amarelo" if "warn" in status else "verde"


def checar_opt_in(grafo: dict[str, Any]) -> dict[str, Any]:
    """§5.3: `channel.*` sem opt-in configurado é bloqueante — re-checado no pré-voo."""
    canais = [n for n in grafo.get("nodes") or [] if str(n.get("type", "")) in _CANAIS_JGC]
    sem_opt_in = [str(n["id"]) for n in canais if not (n.get("data") or {}).get("optIn")]
    evidencia = {"nos_canal": [str(n["id"]) for n in canais], "sem_opt_in": sem_opt_in}
    return item("opt_in", "fail" if sem_opt_in else "pass", evidencia)


def checar_frescor_hybris(frescor: dict[str, Any]) -> dict[str, Any]:
    """Freshness Hybris (fixture §11): D-1 (≤24h) pass · ≤48h warn · >48h/ausente fail."""
    fonte = frescor.get("hybris_base_clientes") or {}
    horas = fonte.get("atualizado_ha_horas")
    evidencia = {
        "fonte": "hybris_base_clientes",
        "atualizado_ha_horas": horas,
        "sla_ciclo_h": FRESCOR_HYBRIS_PASS_H,
    }
    if horas is None:
        return item("frescor_hybris", "fail", evidencia | {"detalhe": "fonte sem frescor"})
    horas = float(horas)
    if horas <= FRESCOR_HYBRIS_PASS_H:
        return item("frescor_hybris", "pass", evidencia)
    if horas <= FRESCOR_HYBRIS_WARN_H:
        return item("frescor_hybris", "warn", evidencia | {"detalhe": "um ciclo D-1 perdido"})
    return item("frescor_hybris", "fail", evidencia | {"detalhe": "frescor além de 2 ciclos"})


def lint_ampscript(texto: str) -> list[str]:
    """Lint AMPscript SIMPLES (§8-M9) — determinístico, sem parser pleno."""
    problemas: list[str] = []
    if texto.count("%%[") != texto.count("]%%"):
        problemas.append("blocos %%[ ... ]%% desbalanceados")
    if texto.count("%%=") != texto.count("=%%"):
        problemas.append("expressões inline %%= ... =%% desbalanceadas")
    return problemas


def checar_lint_ampscript(conteudos: dict[str, str]) -> dict[str, Any]:
    """Lint sobre todo conteúdo com AMPscript ({origem: texto}); sem conteúdo ⇒ pass."""
    problemas = {
        origem: erros for origem, texto in conteudos.items() if (erros := lint_ampscript(texto))
    }
    evidencia: dict[str, Any] = {"conteudos_varridos": sorted(conteudos), "problemas": problemas}
    return item("lint_ampscript", "fail" if problemas else "pass", evidencia)


def checar_limites_sfmc(recursos: list[dict[str, Any]]) -> dict[str, Any]:
    """Limites SFMC (LIMITES_SFMC) sobre os recursos compilados (§5.4.1)."""
    violacoes: list[dict[str, Any]] = []
    for recurso in recursos:
        chave, tipo, payload = recurso["recurso"], recurso["tipo_sfmc"], recurso["payload"]
        if len(str(chave)) > LIMITES_SFMC["chave_max"]:
            violacoes.append({"recurso": chave, "limite": "chave_max", "valor": len(str(chave))})
        nome = str(payload.get("name", ""))
        if len(nome) > LIMITES_SFMC["nome_max"]:
            violacoes.append({"recurso": chave, "limite": "nome_max", "valor": len(nome)})
        if tipo == "journey":
            n_atividades = len(payload.get("activities") or [])
            if n_atividades > LIMITES_SFMC["activities_max"]:
                violacoes.append(
                    {"recurso": chave, "limite": "activities_max", "valor": n_atividades}
                )
        if tipo == "dataExtension":
            n_campos = len(payload.get("fields") or [])
            if n_campos > LIMITES_SFMC["campos_de_max"]:
                violacoes.append({"recurso": chave, "limite": "campos_de_max", "valor": n_campos})
    evidencia = {
        "limites": dict(LIMITES_SFMC),
        "recursos_verificados": len(recursos),
        "violacoes": violacoes,
    }
    return item("limites_sfmc", "fail" if violacoes else "pass", evidencia)
