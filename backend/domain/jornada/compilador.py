"""Compilador do twin — geração DETERMINÍSTICA dos recursos SFMC (SDD §5.4, §8-M9).

CÓDIGO PURO, zero I/O e **LLM PROIBIDO neste caminho** (§5.4): mesmo JGC + mesmo hash
⇒ mesmos payloads byte a byte (é isso que os golden files do M9-A2 verificam).

`compilar_recursos(grafo, hash_jgc)` resolve as dependências na ordem do §5.4.1
(DEs → EventDefs → Assets → Journey → Automations) e devolve a lista de recursos
`{recurso, tipo_sfmc, no_jgc, payload}`:

- **dataExtension** — um por `deRef` distinto (entrySource/updateContact/goal); a
  externalKey da DE é o próprio `deRef` (a DE é referenciada pelo nome no JGC §5.2 e
  SOBREVIVE a novas versões do grafo — destruí-la é sempre aviso destrutivo §5.4.3).
- **eventDefinition** — por `entrySource`; `eventDefinitionKey` = externalKey §5.4.1.
- **asset** — por `channel.*`; `customerKey` = externalKey; assetType por canal.
- **journey (interaction)** — um por grafo; `key` = `jrn-{hash[0:12]}`; triggers dos
  entrySources; activities = demais nós com `outcomes` vindos da adjacência ÚNICA
  (`domain/jornada/adjacencia.py` — arestas **e** regras de `decisionSplit` que
  carregam `to` direto; emenda D07 estendida ao compilador no UAT #5).
- **automation** — por `entrySource` com `modo=scheduled` (agenda do disparo).

Nó `exception` (§5.2) NÃO compila: `GrafoNaoCompilavel` (bloqueia publish).
O XML SOAP (`corpo_soap_create`) espelha o template do adapter (adapters/sfmc/
cliente.py) — corpo do CreateRequest sem envelope/token (golden `*.xml`).
"""

from typing import Any
from xml.sax.saxutils import escape

from domain.jornada.adjacencia import saidas_do_grafo
from domain.jornada.erros import GrafoNaoCompilavel
from domain.jornada.sfmc_preview import COMPILA_PARA, external_key

NS_PARTNER = "http://exacttarget.com/wsdl/partnerAPI"
XSI = "http://www.w3.org/2001/XMLSchema-instance"

# Ordem de dependência do plan/apply (§5.4.1); destruição ocorre na ordem inversa.
ORDEM_TIPOS: tuple[str, ...] = (
    "dataExtension",
    "eventDefinition",
    "asset",
    "journey",
    "automation",
)

# Recursos criados via SOAP (DataExtension/Automation — §11.1); demais via REST.
TIPOS_SOAP: tuple[str, ...] = ("dataExtension", "automation")

# Avisos destrutivos OBRIGATÓRIOS (§5.4.3)
AVISO_RECRIAR_EVENT_SOURCE = (
    "DESTRUTIVO: recriar o Event Source reinicia os contatos em espera (§5.4.3)."
)
AVISO_DESTRUIR_DE = "DESTRUTIVO: destruir a Data Extension apaga os dados nela contidos (§5.4.3)."

# assetType SFMC por canal (determinístico; e-mail = htmlemail, demais = textblock)
_ASSET_TYPE_POR_CANAL: dict[str, dict[str, Any]] = {
    "channel.email": {"id": 208, "name": "htmlemail"},
    "channel.sms": {"id": 195, "name": "textblock"},
    "channel.push": {"id": 195, "name": "textblock"},
    "channel.whatsapp": {"id": 195, "name": "textblock"},
    "channel.rcs": {"id": 195, "name": "textblock"},
}

# Campos default da DE (o JGC §5 não descreve o schema da DE — contrato mínimo)
_CAMPOS_DE: list[dict[str, str]] = [{"name": "SubscriberKey", "fieldType": "Text"}]


def chave_journey(hash_jgc: str) -> str:
    """externalKey do journey (interaction): `jrn-{hash[0:12]}` (§5.4.1)."""
    return f"jrn-{hash_jgc[:12]}"


def _recurso(tipo: str, chave: str, no_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"recurso": chave, "tipo_sfmc": tipo, "no_jgc": no_id, "payload": payload}


def compilar_recursos(grafo: dict[str, Any], hash_jgc: str) -> list[dict[str, Any]]:
    """Recursos SFMC do grafo na ordem de dependência §5.4.1 — determinístico."""
    nodes: list[dict[str, Any]] = list(grafo.get("nodes") or [])
    # Adjacência pela fonte ÚNICA (D07 · UAT #5): a cópia inline daqui iterava só
    # `edges` e todo `decisionSplit` roteado por `data.regras[].to` saía sem NENHUMA
    # saída — o JB importava o split com os nós a jusante órfãos, e o drift comparava
    # contra esse payload já errado.
    saidas = saidas_do_grafo(grafo)
    os_codigo = str((grafo.get("meta") or {}).get("osCodigo", ""))

    excecoes = [str(n["id"]) for n in nodes if n.get("type") == "exception"]
    if excecoes:
        raise GrafoNaoCompilavel(excecoes)

    recursos: list[dict[str, Any]] = []

    # 1) DataExtensions — um por deRef distinto, na ordem dos nós (dedupe determinístico)
    de_vistas: set[str] = set()
    for no in nodes:
        de_ref = (no.get("data") or {}).get("deRef")
        if not de_ref or de_ref in de_vistas:
            continue
        de_vistas.add(str(de_ref))
        recursos.append(
            _recurso(
                "dataExtension",
                str(de_ref),
                str(no["id"]),
                {"customerKey": str(de_ref), "name": str(de_ref), "fields": _CAMPOS_DE},
            )
        )

    # 2) Event Definitions — por entrySource (§5.2: Event Definition + Entry Source)
    entradas = [n for n in nodes if n.get("type") == "entrySource"]
    for no in entradas:
        no_id, data = str(no["id"]), dict(no.get("data") or {})
        chave = external_key(hash_jgc, no_id)
        recursos.append(
            _recurso(
                "eventDefinition",
                chave,
                no_id,
                {
                    "eventDefinitionKey": chave,
                    "name": f"Entrada {os_codigo} ({no_id})",
                    "type": "APIEvent",
                    "dataExtensionName": str(data.get("deRef", "")),
                },
            )
        )

    # 3) Assets — por channel.* (assetRef vira content; customerKey = externalKey)
    for no in nodes:
        tipo = str(no.get("type", ""))
        if tipo not in _ASSET_TYPE_POR_CANAL:
            continue
        no_id, data = str(no["id"]), dict(no.get("data") or {})
        chave = external_key(hash_jgc, no_id)
        recursos.append(
            _recurso(
                "asset",
                chave,
                no_id,
                {
                    "customerKey": chave,
                    "name": f"{tipo} {no_id} — {os_codigo}",
                    "assetType": _ASSET_TYPE_POR_CANAL[tipo],
                    "content": str(data.get("assetRef", "")),
                },
            )
        )

    # 4) Journey (interaction) — entrySources viram triggers; demais nós, activities
    atividades: list[dict[str, Any]] = []
    for no in nodes:
        tipo = str(no.get("type", ""))
        if tipo == "entrySource":
            continue
        no_id = str(no["id"])
        tipo_sfmc, _ = COMPILA_PARA.get(tipo, (None, "—"))
        atividades.append(
            {
                "key": external_key(hash_jgc, no_id),
                "type": str(tipo_sfmc),
                "arguments": dict(no.get("data") or {}),
                "outcomes": [
                    {
                        "key": str(a.get("id")),
                        "next": external_key(hash_jgc, str(a.get("to"))),
                        "cond": a.get("cond"),
                    }
                    for a in saidas.get(no_id, [])
                ],
            }
        )
    recursos.append(
        _recurso(
            "journey",
            chave_journey(hash_jgc),
            "*",
            {
                "key": chave_journey(hash_jgc),
                "name": os_codigo,
                "workflowApiVersion": 1.0,
                "triggers": [
                    {
                        "key": external_key(hash_jgc, str(n["id"])),
                        "type": "APIEvent",
                        "arguments": {"eventDefinitionKey": external_key(hash_jgc, str(n["id"]))},
                    }
                    for n in entradas
                ],
                "activities": atividades,
            },
        )
    )

    # 5) Automations — entrySource agendado (modo=scheduled §5.2) vira Automation
    for no in entradas:
        data = dict(no.get("data") or {})
        if data.get("modo") != "scheduled":
            continue
        no_id = str(no["id"])
        chave = f"{external_key(hash_jgc, no_id)}-agenda"
        recursos.append(
            _recurso(
                "automation",
                chave,
                no_id,
                {"customerKey": chave, "name": f"Agenda {os_codigo} ({no_id})"},
            )
        )

    return recursos


def corpo_soap_create(tipo_sfmc: str, payload: dict[str, Any]) -> str:
    """Corpo do CreateRequest SOAP (sem envelope/token) — espelha o template do
    adapter (adapters/sfmc/cliente.py); é o que os golden `*.xml` congelam (A2)."""
    if tipo_sfmc == "dataExtension":
        campos = "".join(
            f"<Field><Name>{escape(str(c['name']))}</Name>"
            f"<FieldType>{escape(str(c['fieldType']))}</FieldType></Field>"
            for c in payload.get("fields", [])
        )
        conteudo = (
            f"<CustomerKey>{escape(str(payload['customerKey']))}</CustomerKey>"
            f"<Name>{escape(str(payload['name']))}</Name><Fields>{campos}</Fields>"
        )
        objeto = "DataExtension"
    elif tipo_sfmc == "automation":
        conteudo = (
            f"<CustomerKey>{escape(str(payload['customerKey']))}</CustomerKey>"
            f"<Name>{escape(str(payload['name']))}</Name>"
        )
        objeto = "Automation"
    else:
        raise ValueError(f"Tipo sem representação SOAP: {tipo_sfmc!r} (§11.1)")
    return (
        f'<CreateRequest xmlns="{NS_PARTNER}" xmlns:xsi="{XSI}">'
        f'<Objects xsi:type="{objeto}">{conteudo}</Objects></CreateRequest>'
    )
