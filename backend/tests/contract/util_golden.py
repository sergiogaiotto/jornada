"""Fixture e serialização dos GOLDEN FILES do M9-A2 (SDD §8-M9).

`tests/contract/golden/` congela, byte a byte, os payloads que o compilador (§5.4 —
determinístico, zero LLM) gera para o JGC de referência abaixo: REST em JSON
(eventDefinition, asset, journey) e SOAP em XML (DataExtension, Automation — corpo do
CreateRequest, sem envelope/token). Qualquer mudança no compilador que altere um byte
dos payloads QUEBRA o aceite `test_M9_A2` — mudanças intencionais exigem regenerar os
golden files com `python -m tests.contract.util_golden` (e emenda no CHANGELOG-SDD.md).

O JGC de referência é FIXO (osCodigo OS-2026-0457 — §11.4) e o hash é o sha256
canônico (canonico.py): mesmos bytes em qualquer máquina/execução.
"""

import json
from pathlib import Path
from typing import Any

from domain.jornada.canonico import hash_jgc
from domain.jornada.compilador import TIPOS_SOAP, compilar_recursos, corpo_soap_create

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# JGC §5 de referência (OS demo §11.4): entrada AGENDADA (gera Automation §5.4.1) →
# randomSplit 90/10 (holdout) → wait → e-mail → decisionSplit → goal; holdout → exit.
#
# Os DOIS `decisionSplit` são deliberados (achado 3 do UAT #5): até aqui o JGC de
# referência não tinha NENHUM, e por isso o CI ficou verde enquanto o compilador
# descartava o roteamento por `data.regras[].to` — n7 cobre essa forma e n8 cobre a
# forma clássica (regra sem `to`, destino na aresta `cond`). Nenhum dos dois cria
# recurso SFMC novo (só activities no journey), então as contagens do M9-A2 seguem.
JGC_GOLDEN: dict[str, Any] = {
    "jgcVersion": "1.0",
    "meta": {
        "osCodigo": "OS-2026-0457",
        "tenant": "torre-movel",
        "reentrada": "nao",
        "quietHours": {"inicio": "20:00", "fim": "08:00"},
    },
    "nodes": [
        {
            "id": "n1",
            "type": "entrySource",
            "data": {
                "deRef": "DE_457_entrada",
                "modo": "scheduled",
                "agenda": "FREQ=DAILY;BYHOUR=9",
                "reentrada": "nao",
            },
        },
        {
            "id": "n2",
            "type": "randomSplit",
            "data": {"braços": [{"id": "tratado", "pct": 90}, {"id": "holdout", "pct": 10}]},
        },
        {"id": "n3", "type": "wait", "data": {"duracao": "PT4H"}},
        {
            "id": "n4",
            "type": "channel.email",
            "data": {"assetRef": "asset-email-457", "optIn": True, "throttlePorHora": 25000},
        },
        {"id": "n5", "type": "goal", "data": {"metrica": "conversion", "deRef": "DE_457_conv"}},
        {"id": "n6", "type": "exit", "data": {"motivo": "holdout"}},
        {
            "id": "n7",  # roteamento por `data.regras[].to` (forma da seed §11.4)
            "type": "decisionSplit",
            "data": {
                "regras": [
                    {"expr": "abriu_email == false", "to": "n5"},
                    {"expr": "senao", "to": "n8"},
                ]
            },
        },
        {
            "id": "n8",  # roteamento clássico: regra sem `to`, destino na aresta `cond`
            "type": "decisionSplit",
            "data": {"regras": [{"id": "vip", "cond": "score > 90"}, {"id": "resto"}]},
        },
    ],
    "edges": [
        {"id": "e1", "from": "n1", "to": "n2", "cond": None},
        {"id": "e2", "from": "n2", "to": "n3", "cond": "tratado"},
        {"id": "e3", "from": "n2", "to": "n6", "cond": "holdout"},
        {"id": "e4", "from": "n3", "to": "n4", "cond": None},
        {"id": "e5", "from": "n4", "to": "n7", "cond": None},
        {"id": "e6", "from": "n8", "to": "n5", "cond": "vip"},
        {"id": "e7", "from": "n8", "to": "n6", "cond": "resto"},
    ],
}

HASH_GOLDEN = hash_jgc(JGC_GOLDEN)


def recursos_golden() -> list[dict[str, Any]]:
    """Recursos compilados do JGC de referência (ordem §5.4.1) — determinístico."""
    return compilar_recursos(JGC_GOLDEN, HASH_GOLDEN)


def nome_arquivo(item: dict[str, Any]) -> str:
    """Nome estável por recurso: SOAP → .xml, REST → .json."""
    tipo, no = str(item["tipo_sfmc"]), str(item["no_jgc"])
    if tipo == "dataExtension":
        return f"de_{item['recurso']}.xml"
    if tipo == "automation":
        return f"automation_{no}.xml"
    if tipo == "eventDefinition":
        return f"eventdef_{no}.json"
    if tipo == "asset":
        return f"asset_{no}.json"
    return "journey.json"


def serializar(item: dict[str, Any]) -> bytes:
    """Bytes canônicos do payload: XML do CreateRequest (SOAP) ou JSON ordenado."""
    if item["tipo_sfmc"] in TIPOS_SOAP:
        return (corpo_soap_create(str(item["tipo_sfmc"]), item["payload"]) + "\n").encode("utf-8")
    texto = json.dumps(item["payload"], ensure_ascii=False, indent=2, sort_keys=True)
    return (texto + "\n").encode("utf-8")


def arquivos_golden() -> dict[str, bytes]:
    """{nome do arquivo → bytes canônicos} de todos os recursos do JGC de referência."""
    return {nome_arquivo(item): serializar(item) for item in recursos_golden()}


def regenerar() -> list[str]:
    """(Re)escreve `tests/contract/golden/` — só para mudanças INTENCIONAIS de contrato."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    nomes = []
    for nome, conteudo in sorted(arquivos_golden().items()):
        (GOLDEN_DIR / nome).write_bytes(conteudo)
        nomes.append(nome)
    return nomes


if __name__ == "__main__":
    for nome in regenerar():
        print(nome)
