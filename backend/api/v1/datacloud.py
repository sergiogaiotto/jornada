"""Rotas do M5 · Data Cloud / T5a (SDD §8-M5) — tag OpenAPI `datacloud`.

`GET /datacloud/segmentos` (cache+frescor — consulta, não cópia) ·
`GET /datacloud/segmentos/{id}/relatorio` (bruto→elegível→líquido→sobreposição +
volume de abordagem por canal pós caps/quiet/colisões — colisões do governor, A2) ·
`POST /datacloud/segmentos/{id}/usar` (vira `segmento` origem data_cloud com lineage) ·
`GET /datacloud/segmentos/{id}/relatorio.docx` (documento executivo determinístico).

Erros: domínio → RFC-7807 (mapa do M1 via RotaComErrosDeDominio: NaoEncontrado→404).
RBAC (§8-M0): leitura para qualquer autenticado; `usar` exige analista|lider.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict

from adapters.documentos.docx_portao import GeradorDocxPortao
from api.v1.audiencia import SegmentoOut, Servico
from api.v1.os_governanca import Autenticado, Escritor, RotaComErrosDeDominio, Tenant

_gerador = GeradorDocxPortao()

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class DcSegmentoOut(BaseModel):
    """Linha de `dc_segment_cache` (§4.1) — consulta ao Data Cloud, não cópia (T5a)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    nome: str | None
    criterios_resumo: str | None
    membros: int | None
    dmos: list[str]
    republicado_em: datetime | None  # frescor da publicação no Data Cloud
    ciclo: str | None
    status: str | None
    atualizado_em: datetime | None  # frescor da consulta (cache §8-M5)


class RelatorioDcOut(BaseModel):
    """Relatório T5a (§8-M5): funil, waterfall, sobreposição, volume por canal, frescor."""

    segmento: dict[str, Any]
    funil: dict[str, int]  # {bruto, elegivel, liquido}
    waterfall: list[dict[str, Any]]
    sobreposicao: dict[str, int]
    volume_abordagem: dict[str, Any]  # {canal: {n, pct}} — A2
    colisoes: dict[str, int]  # por canal — vêm do governor (A2)
    frescor: dict[str, str]  # {fonte: ultima_atualizacao} — A4


class UsarIn(BaseModel):
    os_id: uuid.UUID  # OS que passa a usar o segmento (lineage)


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaComErrosDeDominio, tags=["datacloud"])


@router.get("/datacloud/segmentos", response_model=list[DcSegmentoOut])
async def listar_segmentos(
    tenant: Tenant, servico: Servico, _user: Autenticado
) -> list[DcSegmentoOut]:
    """Segmentos publicados no Data Cloud (4 nas fixtures §11.2); a consulta atualiza
    `dc_segment_cache` com frescor (republicado_em + atualizado_em)."""
    return [
        DcSegmentoOut.model_validate(entrada) for entrada in servico.listar_segmentos_dc(tenant)
    ]


@router.get("/datacloud/segmentos/{segmento_id}/relatorio", response_model=RelatorioDcOut)
async def relatorio(
    segmento_id: str, tenant: Tenant, servico: Servico, _user: Autenticado
) -> RelatorioDcOut:
    """Relatório do segmento (§8-M5): bruto→elegível→líquido→sobreposição + volume de
    abordagem por canal pós caps/quiet hours/colisões (A2) + frescor por fonte (A4)."""
    return RelatorioDcOut.model_validate(servico.relatorio_dc(tenant, segmento_id))


@router.get("/datacloud/segmentos/{segmento_id}/relatorio.docx")
async def relatorio_docx(
    segmento_id: str, tenant: Tenant, servico: Servico, _user: Autenticado
) -> Response:
    """Documento executivo do relatório (§8-M5) — geração DETERMINÍSTICA (sem LLM)."""
    conteudo = _gerador.relatorio_segmento(relatorio=servico.relatorio_dc(tenant, segmento_id))
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{segmento_id}-relatorio.docx"'},
    )


@router.post("/datacloud/segmentos/{segmento_id}/usar", status_code=201, response_model=SegmentoOut)
async def usar_segmento(
    segmento_id: str, payload: UsarIn, tenant: Tenant, servico: Servico, user: Escritor
) -> SegmentoOut:
    """Vira `segmento` origem data_cloud com lineage (dc_segment_id + contagens/frescor
    da consulta — T5a: consulta, não cópia)."""
    return SegmentoOut.model_validate(
        servico.usar_segmento_dc(tenant, segmento_id, os_id=payload.os_id, actor=user.email)
    )
