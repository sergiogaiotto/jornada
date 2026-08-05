"""mock-datacloud — simulação do Data Cloud para dev/CI (SDD §11.2, completado no M5).

Token OAuth + `GET /api/v2/segments` (4 segmentos das fixtures do plano) + query count
+ relatório (contagens T5a). Fonte ÚNICA de fixtures: `mocks/seeds/datacloud_segmentos.json`
(o mesmo arquivo do adapter de fixtures do backend). Frescor relativo das seeds vira
timestamp absoluto ancorado em `_NOW` fixo (respostas determinísticas).
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

app = FastAPI(title="mock-datacloud", version="1.0.0")

_NOW = datetime(2026, 8, 4, 6, 0, tzinfo=UTC)
_AQUI = Path(__file__).resolve()
_CANDIDATOS = (
    _AQUI.parents[1] / "seeds" / "datacloud_segmentos.json",  # layout do repo (mocks/seeds)
    _AQUI.parent / "seeds" / "datacloud_segmentos.json",  # layout do container (COPY seeds/)
)
_SEEDS = next((c for c in _CANDIDATOS if c.exists()), _CANDIDATOS[0])


def _segmentos() -> list[dict[str, Any]]:
    return list(json.loads(_SEEDS.read_text(encoding="utf-8")).get("segmentos", []))


def _publico(segmento: dict[str, Any]) -> dict[str, Any]:
    """Forma pública da listagem: sem o bloco `relatorio`; frescor absoluto ISO."""
    dados = {chave: valor for chave, valor in segmento.items() if chave != "relatorio"}
    horas = float(dados.pop("republicado_ha_horas", 0.0))
    dados["republicado_em"] = (_NOW - timedelta(hours=horas)).isoformat()
    return dados


def _obter(segment_id: str) -> dict[str, Any]:
    for segmento in _segmentos():
        if segmento.get("id") == segment_id:
            return segmento
    raise HTTPException(status_code=404, detail=f"segmento {segment_id} não existe")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/oauth/token")
def token() -> dict[str, Any]:
    return {
        "access_token": "mock-datacloud-access-token",
        "token_type": "Bearer",
        "expires_in": 7200,
        "instance_url": "http://mock-datacloud:8081",
    }


@app.get("/api/v2/segments")
def list_segments() -> dict[str, Any]:
    segmentos = [_publico(s) for s in _segmentos()]
    return {"segments": segmentos, "total": len(segmentos)}


@app.get("/api/v2/segments/{segment_id}")
def get_segment(segment_id: str) -> dict[str, Any]:
    return _publico(_obter(segment_id))


@app.get("/api/v2/segments/{segment_id}/count")
def query_count(segment_id: str) -> dict[str, Any]:
    """Query count (§11.2) — contagem de membros publicada."""
    segmento = _obter(segment_id)
    return {"id": segment_id, "membros": segmento.get("membros"), "contado_em": _NOW.isoformat()}


@app.get("/api/v2/segments/{segment_id}/report")
def report(segment_id: str) -> dict[str, Any]:
    """Contagens do relatório T5a (§8-M5): supressões (7 listas), opt-in, sobreposição,
    insumos de volume por canal (colisões do governor) e frescor por fonte."""
    relatorio = _obter(segment_id).get("relatorio")
    if relatorio is None:
        raise HTTPException(status_code=404, detail=f"segmento {segment_id} sem relatório")
    return dict(relatorio)
