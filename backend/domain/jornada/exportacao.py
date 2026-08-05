"""Exportação da jornada (§8-M7, emenda 2026-08-05) — CÓDIGO PURO, zero LLM (§10.6).

`GET /jornadas/{id}/export?formato=json|xml` serve DOIS consumidores com a MESMA spec:

- **JSON** — a spec de *interaction* do Journey Builder (REST
  `/interaction/v1/interactions`), montada REAPROVEITANDO o compilador M9
  (`compilar_recursos` §5.4): `key = jrn-{hash[0:12]}`, `triggers` dos entrySources,
  `activities` com externalKeys idempotentes `jrn-{hash[0:12]}-{noId}` (§5.4.1) e
  `goals` derivados dos nós `goal` (§5.2). **É o formato de import nativo do JB** —
  o Journey Builder NÃO importa XML.
- **XML** — serialização determinística e canônica da MESMA spec
  (`<Interaction><Activities><Activity type=...>`), validável contra o XSD
  `domain/jornada/journey_export.xsd`, com `<Manifest>` embutido (hash JGC, versao,
  geradoEm via ClockPort, plataforma Jornada). Atende integração/auditoria
  corporativa (sistemas que exigem XML + schema), NÃO o import do JB.

Determinismo (aceite M7-B5): mesmo grafo + mesmo clock ⇒ mesmos bytes. Ordenação
vem do compilador (ordem dos nós do JGC); argumentos são ordenados por nome; JSON
canônico usa `sort_keys` (mesma serialização dos golden files M9-A2).
"""

import json
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from domain.jornada.canonico import canonicalizar
from domain.jornada.compilador import compilar_recursos

PLATAFORMA = "Jornada"


def montar_interaction(grafo: dict[str, Any], hash_jgc: str) -> dict[str, Any]:
    """Spec COMPLETA da interaction (REST /interaction/v1/interactions) a partir do
    recurso `journey` do compilador M9 (§5.4) + `goals` derivados das activities
    `type=goal` (no import nativo do JB, goals são um array próprio; as activities
    do compilador são preservadas na íntegra — contrato dos golden files M9-A2)."""
    journey = next(r for r in compilar_recursos(grafo, hash_jgc) if r["tipo_sfmc"] == "journey")
    interaction = dict(journey["payload"])
    interaction["goals"] = [
        {"key": a["key"], "arguments": dict(a["arguments"])}
        for a in interaction["activities"]
        if a["type"] == "goal"
    ]
    return interaction


def export_json(grafo: dict[str, Any], hash_jgc: str) -> bytes:
    """Bytes canônicos da interaction (JSON ordenado + \\n final — padrão golden M9).

    Import nativo do JB: este JSON é o corpo do POST /interaction/v1/interactions.
    Determinístico pelo grafo sozinho (nenhum relógio envolvido).
    """
    texto = json.dumps(
        montar_interaction(grafo, hash_jgc), ensure_ascii=False, indent=2, sort_keys=True
    )
    return (texto + "\n").encode("utf-8")


# ------------------------------------------------------------------ XML canônico


def _argumento_xml(valor: Any) -> str:
    """Valor do `<Argument>`: string vai crua; bool/None/números/estruturas usam a
    forma canônica JSON (canonico.py) — determinístico por construção."""
    if isinstance(valor, str):
        return valor
    return canonicalizar(valor)


def _arguments_xml(arguments: dict[str, Any], indent: str) -> list[str]:
    if not arguments:
        return [f"{indent}<Arguments/>"]
    linhas = [f"{indent}<Arguments>"]
    for nome in sorted(arguments):
        linhas.append(
            f"{indent}  <Argument nome={quoteattr(nome)}>"
            f"{escape(_argumento_xml(arguments[nome]))}</Argument>"
        )
    linhas.append(f"{indent}</Arguments>")
    return linhas


def _outcomes_xml(outcomes: list[dict[str, Any]], indent: str) -> list[str]:
    if not outcomes:
        return [f"{indent}<Outcomes/>"]
    linhas = [f"{indent}<Outcomes>"]
    for saida in outcomes:
        atributos = f"key={quoteattr(str(saida['key']))} next={quoteattr(str(saida['next']))}"
        if saida.get("cond") is not None:
            atributos += f" cond={quoteattr(str(saida['cond']))}"
        linhas.append(f"{indent}  <Outcome {atributos}/>")
    linhas.append(f"{indent}</Outcomes>")
    return linhas


def export_xml(grafo: dict[str, Any], hash_jgc: str, *, versao: int, gerado_em: datetime) -> bytes:
    """XML determinístico e canônico da MESMA spec do export JSON, com manifest
    embutido (hash JGC, versao, geradoEm — ClockPort, plataforma Jornada), válido
    contra `journey_export.xsd`. Mesmo grafo + mesmo clock ⇒ mesmos bytes (M7-B5).

    Honestidade documental: o Journey Builder importa JSON, não XML — este formato
    existe para integração/auditoria corporativa (schema verificável).
    """
    spec = montar_interaction(grafo, hash_jgc)
    linhas = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<Interaction key={quoteattr(str(spec['key']))} name={quoteattr(str(spec['name']))} "
        f"workflowApiVersion={quoteattr(str(spec['workflowApiVersion']))}>",
        f"  <Manifest hashJgc={quoteattr(hash_jgc)} versao={quoteattr(str(versao))} "
        f"geradoEm={quoteattr(gerado_em.isoformat())} plataforma={quoteattr(PLATAFORMA)}/>",
    ]
    if spec["triggers"]:
        linhas.append("  <Triggers>")
        for trigger in spec["triggers"]:
            linhas.append(
                f"    <Trigger key={quoteattr(str(trigger['key']))} "
                f"type={quoteattr(str(trigger['type']))}>"
            )
            linhas.extend(_arguments_xml(dict(trigger.get("arguments") or {}), "      "))
            linhas.append("    </Trigger>")
        linhas.append("  </Triggers>")
    else:
        linhas.append("  <Triggers/>")
    if spec["activities"]:
        linhas.append("  <Activities>")
        for atividade in spec["activities"]:
            linhas.append(
                f"    <Activity key={quoteattr(str(atividade['key']))} "
                f"type={quoteattr(str(atividade['type']))}>"
            )
            linhas.extend(_arguments_xml(dict(atividade.get("arguments") or {}), "      "))
            linhas.extend(_outcomes_xml(list(atividade.get("outcomes") or []), "      "))
            linhas.append("    </Activity>")
        linhas.append("  </Activities>")
    else:
        linhas.append("  <Activities/>")
    if spec["goals"]:
        linhas.append("  <Goals>")
        for goal in spec["goals"]:
            linhas.append(f"    <Goal key={quoteattr(str(goal['key']))}>")
            linhas.extend(_arguments_xml(dict(goal.get("arguments") or {}), "      "))
            linhas.append("    </Goal>")
        linhas.append("  </Goals>")
    else:
        linhas.append("  <Goals/>")
    linhas.append("</Interaction>")
    return ("\n".join(linhas) + "\n").encode("utf-8")
