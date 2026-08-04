"""mock-datacloud — stub mínimo M0 (SDD §11.2).

M0: token + GET /api/v2/segments (4 segmentos) + healthz. M5 completa com as
fixtures integrais do plano (relatórios, query count, frescor Hybris D-1).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException

app = FastAPI(title="mock-datacloud", version="0.1.0")

_NOW = datetime(2026, 8, 4, 6, 0, tzinfo=UTC)

SEGMENTS: list[dict[str, Any]] = [
    {
        "id": "DC-SEG-001",
        "nome": "Pré-pago alto consumo dados",
        "criterios_resumo": "ARPU dados > P75 e recarga últimos 30d",
        "membros": 1_240_580,
        "dmos": ["UnifiedIndividual", "ConsumoDados"],
        "republicado_em": (_NOW - timedelta(hours=6)).isoformat(),
        "ciclo": "diario",
        "status": "ativo",
    },
    {
        "id": "DC-SEG-002",
        "nome": "Pós-pago elegível upgrade 5G",
        "criterios_resumo": "aparelho 5G e plano 4G há mais de 6 meses",
        "membros": 847_312,
        "dmos": ["UnifiedIndividual", "Aparelho", "Plano"],
        "republicado_em": (_NOW - timedelta(hours=12)).isoformat(),
        "ciclo": "diario",
        "status": "ativo",
    },
    {
        "id": "DC-SEG-003",
        "nome": "Churn risk score alto",
        "criterios_resumo": "score churn >= 0.7 nos últimos 7 dias",
        "membros": 312_044,
        "dmos": ["UnifiedIndividual", "ScoreChurn"],
        "republicado_em": (_NOW - timedelta(days=1)).isoformat(),
        "ciclo": "semanal",
        "status": "ativo",
    },
    {
        "id": "DC-SEG-004",
        "nome": "Banda larga sem TV assinada",
        "criterios_resumo": "cliente banda larga sem produto TV",
        "membros": 566_901,
        "dmos": ["UnifiedIndividual", "Produtos"],
        "republicado_em": (_NOW - timedelta(days=2)).isoformat(),
        "ciclo": "semanal",
        "status": "republicando",
    },
]


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
    return {"segments": SEGMENTS, "total": len(SEGMENTS)}


@app.get("/api/v2/segments/{segment_id}")
def get_segment(segment_id: str) -> dict[str, Any]:
    for seg in SEGMENTS:
        if seg["id"] == segment_id:
            return seg
    raise HTTPException(status_code=404, detail=f"segmento {segment_id} não existe")
