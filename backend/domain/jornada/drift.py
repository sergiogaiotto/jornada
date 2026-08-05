"""Monitor de drift twin ↔ SFMC — comparação DETERMINÍSTICA (SDD §5.4.5, §8-M9).

CÓDIGO PURO, zero I/O e **LLM PROIBIDO neste caminho** (§5.4): o serviço (drift_service)
faz o retrieve do estado real atrás da porta SFMC; aqui entra só a decompilação e a
comparação por hash/campos:

- `decompilar(tipo_sfmc, estado_real)` — projeta o recurso lido do SFMC nos MESMOS
  campos que o compilador gera (compilador.py §5.4.1); extras do SFMC (id, status,
  modifiedDate…) são ignorados — drift é sobre o CONTRATO do twin, não sobre metadados.
- `comparar_campos(esperado, real)` — diff campo a campo {campo: {twin, sfmc}}.
- `hash_recurso(campos)` — sha256 do JSON canônico (chaves ordenadas): "compara por
  hash/campos" (§5.4.5); hashes iguais ⇔ diff vazio.
- `avaliar_recurso(...)` — grava a linha `drift_check` (§4.1): `em_sincronia` |
  `drift_sfmc` (editado por fora) | `twin_a_frente` (recurso sumiu do SFMC).
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from domain.jornada.modelos import DriftCheck

# Campos comparados por tipo — exatamente os que o compilador emite (compilador.py).
CAMPOS_POR_TIPO: dict[str, tuple[str, ...]] = {
    "dataExtension": ("customerKey", "name", "fields"),
    "eventDefinition": ("eventDefinitionKey", "name", "type", "dataExtensionName"),
    "asset": ("customerKey", "name", "assetType", "content"),
    "journey": ("key", "name", "workflowApiVersion", "triggers", "activities"),
    "automation": ("customerKey", "name"),
}


def decompilar(tipo_sfmc: str, estado_real: dict[str, Any]) -> dict[str, Any]:
    """Estado real do SFMC → campos comparáveis do twin (decompilação §5.4.5)."""
    campos = CAMPOS_POR_TIPO.get(tipo_sfmc, ())
    return {campo: estado_real[campo] for campo in campos if campo in estado_real}


def hash_recurso(campos: dict[str, Any]) -> str:
    """sha256 do JSON canônico (chaves ordenadas) — a régua do "compara por hash"."""
    canonico = json.dumps(campos, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def comparar_campos(esperado: dict[str, Any], real: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Diff campo a campo: {campo: {twin, sfmc}} para todo campo esperado divergente."""
    return {
        campo: {"twin": valor, "sfmc": real.get(campo)}
        for campo, valor in esperado.items()
        if real.get(campo) != valor
    }


def avaliar_recurso(
    *,
    snapshot_id: uuid.UUID,
    ambiente: str,
    tipo_sfmc: str,
    external_key: str,
    payload_esperado: dict[str, Any],
    estado_real: dict[str, Any] | None,
    agora: datetime,
) -> DriftCheck:
    """Uma linha `drift_check` (§4.1) por recurso verificado — determinística."""
    esperado = {
        campo: valor
        for campo, valor in payload_esperado.items()
        if campo in CAMPOS_POR_TIPO.get(tipo_sfmc, ())
    }
    diff: dict[str, Any] = {
        "ambiente": ambiente,
        "tipo_sfmc": tipo_sfmc,
        "hash_twin": hash_recurso(esperado),
    }
    if estado_real is None:  # twin tem o recurso; SFMC não → twin à frente
        estado = "twin_a_frente"
        diff["hash_sfmc"] = None
        diff["campos"] = {campo: {"twin": v, "sfmc": None} for campo, v in esperado.items()}
    else:
        real = decompilar(tipo_sfmc, estado_real)
        diff["hash_sfmc"] = hash_recurso(real)
        campos = comparar_campos(esperado, real)
        estado = "drift_sfmc" if campos else "em_sincronia"
        diff["campos"] = campos
    return DriftCheck(
        id=uuid.uuid4(),
        snapshot_id=snapshot_id,
        recurso=external_key,
        estado=estado,
        diff=diff,
        resolucao=None,
        checked_at=agora,
    )
