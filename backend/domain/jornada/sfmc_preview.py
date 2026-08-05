"""Prévia SFMC por nó (§8-M7: GET /jornadas/{id}/no/{noId}/sfmc-preview).

JSON DETERMINÍSTICO que o compilador (M9 — §5.4) gerará para o nó: mapeamento
"Compila para" da tabela §5.2 + externalKey idempotente `jrn-{hash[0:12]}-{noId}`
(§5.4.1). LLM PROIBIDO neste caminho (§5.4). Os golden files byte a byte são aceite
do M9 — aqui o contrato é o esqueleto do payload.
"""

from typing import Any

from domain.campanha.erros import NaoEncontrado

# type → (tipo de recurso SFMC, "Compila para" da tabela §5.2)
COMPILA_PARA: dict[str, tuple[str | None, str]] = {
    "entrySource": ("eventDefinition", "Event Definition + Entry Source"),
    "randomSplit": ("randomSplit", "Random Split"),
    "decisionSplit": ("decisionSplit", "Decision Split"),
    "engagementSplit": ("engagementSplit", "Engagement Split"),
    "frequencySplit": ("frequencySplit", "Einstein Frequency ou twin-emulado"),
    "sto": ("sto", "Einstein STO ou twin-emulado (Wait By Attribute com hora ótima)"),
    "wait": ("wait", "Wait"),
    "channel.email": ("emailSend", "Send/Message activity"),
    "channel.sms": ("smsSend", "Send/Message activity"),
    "channel.push": ("pushSend", "Send/Message activity"),
    "channel.whatsapp": ("whatsappSend", "Send/Message activity"),
    "channel.rcs": ("rcsSend", "Send/Message activity"),
    "updateContact": ("updateContact", "Update Contact"),
    "goal": ("goal", "Goal"),
    "exit": ("exit", "Exit"),
    "exception": (None, "— (bloqueia publish até resolução)"),
}


def external_key(hash_jgc: str, no_id: str) -> str:
    """Idempotência do apply (§5.4.1): externalKey = `jrn-{hash[0:12]}-{noId}`."""
    return f"jrn-{hash_jgc[:12]}-{no_id}"


def preview_do_no(grafo: dict[str, Any], hash_jgc: str, no_id: str) -> dict[str, Any]:
    """Prévia determinística do que o compilador gerará para o nó (§8-M7)."""
    no = next(
        (n for n in grafo.get("nodes") or [] if str(n.get("id")) == no_id),
        None,
    )
    if no is None:
        raise NaoEncontrado(f"Nó {no_id!r} não existe no grafo desta jornada (§8-M7).")
    tipo = str(no.get("type", ""))
    tipo_sfmc, compila_para = COMPILA_PARA.get(tipo, (None, "—"))
    saidas = [
        {"id": str(a.get("id")), "to": str(a.get("to")), "cond": a.get("cond")}
        for a in grafo.get("edges") or []
        if str(a.get("from")) == no_id
    ]
    chave = external_key(hash_jgc, no_id)
    preview: dict[str, Any] = {
        "noId": no_id,
        "type": tipo,
        "compilaPara": compila_para,
        "tipoSfmc": tipo_sfmc,
        "externalKey": chave,
        "compilavel": tipo_sfmc is not None,  # exception bloqueia publish (§5.2)
        "payload": {
            "key": chave,
            "name": f"{tipo} {no_id}",
            "type": tipo_sfmc,
            "arguments": dict(no.get("data") or {}),
            "outcomes": saidas,
        },
    }
    if tipo == "exception":
        preview["aviso"] = (
            "Nó de exceção (Adopt Wizard §5.2): não compila — bloqueia publish até resolução."
        )
    return preview
