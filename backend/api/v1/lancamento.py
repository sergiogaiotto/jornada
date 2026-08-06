"""Rotas do M10 · Torre de Lançamento T12 + Monitor T13 (SDD §8-M10, §4.1 `launch`) —
tag OpenAPI `launch`.

`POST /launch/{snapshot}/armar` (exige APPLY OK) · `POST /launch/{id}/avancar-onda`
(portão automático: checa breakers) · `POST /launch/{id}/kill` (2 ETAPAS — solicitar
devolve token de confirmação; confirmar mata) · `POST /launch/{id}/retomar` (SEMPRE
humano — A1; SEV1 exige 2 aprovadores DISTINTOS) · `POST /webhooks/ens` (ingestão
§8-M10 com ASSINATURA VERIFICADA HMAC-sha256 do corpo + guarda-corpo de PII §10.2;
dispara a avaliação automática dos breakers — A1/A2) · `GET /os/{id}/monitor` (parte
2/T13: TODOS os KPIs como par previsto×realizado sobre o Previsto CONGELADO do
snapshot; reconciliação ENS×extract embutida — A3). O job "extracts loader" e a
reconciliação diária NÃO têm endpoint (§8-M10 os define como job; padrão M9-drift):
casos de uso `ServicoLancamento.carregar_extracts`/`reconciliar`, reusáveis pelo
agendador.

**LLM PROIBIDO em todo este caminho (§10.6)** — breakers, kill e retomada são 100%
determinísticos. Erros: mapa RFC-7807 do M1 + BreakerDisparado→409 com `disparos` ·
TelemetriaInvalida→422 · AprovadorRepetido→403 (herança AcaoNaoPermitida).
RBAC (§8-M0): armar/avançar/kill exigem analista|lider; retomar exige lider|aprovador
(retomada é ato de alçada); o webhook NÃO usa Bearer — a assinatura é a credencial
(mesmo racional do link mágico M8); X-Tenant segue obrigatório (§8).
"""

import hashlib
import hmac
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from adapters.fontes.extracts import ExtractsFixtures
from adapters.fontes.lista_supressao import SupressaoFixtures
from adapters.publicacoes import publicacoes_vigentes
from api.v1.compilador import _relogio
from api.v1.os_governanca import (
    Autenticado,
    Escritor,
    Tenant,
    _problema_de_dominio,
    get_repositorio_os,
)
from app.auth import Usuario, require_role
from app.config import get_settings
from app.errors import problem_response
from application.ports.extracts import ExtractsPort
from application.ports.lista_supressao import ListaSupressaoPort
from application.ports.repositorio_lancamento import RepositorioLancamento
from application.services.lancamento_service import ServicoLancamento
from domain.campanha.erros import ErroDominio
from domain.lancamento.erros import BreakerDisparado, TelemetriaInvalida

ASSINATURA_HEADER = "X-ENS-Signature"


class RotaLancamento(APIRoute):
    """Traduções do M10 ANTES do mapa genérico do M1 (padrão RotaAudiencia/M5)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except BreakerDisparado as exc:  # portão automático: pausa/kill já aplicados
                return problem_response(
                    409,
                    "Conflict",
                    detail=exc.motivo,
                    instance=request.url.path,
                    extra={"disparos": exc.disparos, "estado": exc.estado},
                )
            except TelemetriaInvalida as exc:  # PII/contrato §10.2 — nada foi gravado
                return problem_response(
                    422, "Unprocessable Entity", detail=exc.motivo, instance=request.url.path
                )
            except ErroDominio as exc:
                return _problema_de_dominio(exc, request.url.path)

        return handler


# ------------------------------------------------------------------ Dependências


def get_supressao(request: Request) -> ListaSupressaoPort:
    """7 listas atrás de porta (§2.1): dev/teste = fixtures (§11.4 — nenhuma rede);
    o adapter Postgres (`lista_supressao` §4.1) entra via `app.state.supressao`."""
    supressao = getattr(request.app.state, "supressao", None)
    if supressao is None:
        supressao = SupressaoFixtures()
        request.app.state.supressao = supressao
    return supressao


def get_extracts(request: Request) -> ExtractsPort:
    """Extracts atrás de porta (§2.1): dev/teste = fixture CSV (§11 — nenhuma rede);
    o adapter real (tracking extracts SFMC) entra via `app.state.extracts`."""
    extracts = getattr(request.app.state, "extracts", None)
    if extracts is None:
        extracts = ExtractsFixtures()
        request.app.state.extracts = extracts
    return extracts


def get_servico_lancamento(request: Request) -> ServicoLancamento:
    """Mesma instância de repositório (app.state) — RepositorioOsMemoria implementa
    todas as portas (tipagem estrutural §2.1)."""
    repositorio = get_repositorio_os(request)
    return ServicoLancamento(
        cast(RepositorioLancamento, repositorio),
        _relogio,
        get_supressao(request),
        # breakers congelados no armar saem da política VIGENTE (achado 8 UAT #5)
        publicacoes_vigentes(repositorio),
        extracts=get_extracts(request),
    )


_papel_retomada = require_role("lider", "aprovador")
Retomador = Annotated[Usuario, Depends(_papel_retomada)]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class LaunchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_id: uuid.UUID
    ondas: list[dict[str, Any]]
    onda_atual: int
    estado: Literal["armado", "em_rampa", "pausado_breaker", "morto", "concluido"]
    breakers: dict[str, Any]
    eventos: list[dict[str, Any]]


class KillIn(BaseModel):
    confirmacao: str | None = None  # None = etapa 1 (solicita); token = etapa 2 (confirma)


class KillOut(BaseModel):
    etapa: Literal[1, 2]
    confirmacao: str | None  # token devolvido UMA vez na etapa 1
    launch: LaunchOut


class RetomarOut(BaseModel):
    retomado: bool
    aprovacoes: int
    exigidas: int  # 2 quando há incidente SEV1 aberto (§8-M10)
    launch: LaunchOut


class EventoEnsIn(BaseModel):
    """Evento ENS → linha de `telemetry_event` (§4.1). NUNCA PII (§10.2)."""

    os_id: uuid.UUID
    tipo: Literal["sent", "delivered", "open", "click", "bounce", "optout", "conversion"]
    ts: datetime
    canal: Literal["email", "sms", "push", "whatsapp", "rcs"] | None = None
    no_jgc: str | None = None
    contato_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    payload: dict[str, Any] | None = None


class LoteEnsIn(BaseModel):
    eventos: list[EventoEnsIn] = Field(min_length=1)


class IngestaoOut(BaseModel):
    recebidos: int
    avaliados: list[dict[str, Any]]  # [{launch_id, estado, disparos}] — A1/A2


class MonitorOut(BaseModel):
    """§8-M10 (T13): TODO KPI é PAR `{previsto, realizado}` — o previsto vem só do
    snapshot congelado (§1.1.2); `reconciliacao` embute o ENS×extract corrente + os
    alertas abertos (A3)."""

    os: dict[str, Any]
    snapshot: dict[str, Any]  # {id, hash, previsto_congelado_em}
    launch: dict[str, Any] | None  # launch de referência (None = ainda não armado)
    kpis: dict[str, dict[str, Any]]  # conversoes|lift_pp|roas|custo|receita
    canais: dict[str, dict[str, Any]]  # {canal: {disparos: par, custo: par}}
    metas: dict[str, dict[str, Any]]  # briefing.metas × realizado (par)
    fontes: dict[str, int]  # {ens, extract}
    premissas: list[str]
    reconciliacao: dict[str, Any]  # {limite_pct, por_tipo, divergente, alertas}


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaLancamento, tags=["launch"])


@router.post("/launch/{snapshot_id}/armar", status_code=201, response_model=LaunchOut)
async def armar_launch(
    snapshot_id: uuid.UUID, tenant: Tenant, request: Request, user: Escritor
) -> LaunchOut:
    """§8-M10: arma a Torre para o snapshot — exige APPLY OK (§8-M9) e congela os
    `breakers` da política publicada (§4.1: 'limites da política congelada'). Rampa
    default 1% → 10% → 100%."""
    servico = get_servico_lancamento(request)
    launch = servico.armar(tenant, snapshot_id, actor=user.email)
    return LaunchOut.model_validate(launch)


@router.post("/launch/{launch_id}/avancar-onda", response_model=LaunchOut)
async def avancar_onda(
    launch_id: uuid.UUID, tenant: Tenant, request: Request, user: Escritor
) -> LaunchOut:
    """§8-M10: portão AUTOMÁTICO entre ondas — checa os breakers sobre a telemetria
    da janela; disparo ⇒ pausa (ou kill SEV1) automática + 409 com `disparos`.
    Após a última onda ⇒ `concluido`."""
    servico = get_servico_lancamento(request)
    launch = servico.avancar_onda(tenant, launch_id, actor=user.email)
    return LaunchOut.model_validate(launch)


@router.post("/launch/{launch_id}/kill", response_model=KillOut)
async def kill_launch(
    launch_id: uuid.UUID, payload: KillIn, tenant: Tenant, request: Request, user: Escritor
) -> KillOut:
    """§8-M10: kill switch em 2 ETAPAS — sem `confirmacao` devolve o token da
    solicitação; com o token pendente, mata o launch (incidente `kill_manual` +
    evento `launch.killed` §2.3)."""
    servico = get_servico_lancamento(request)
    resultado = servico.kill(tenant, launch_id, confirmacao=payload.confirmacao, actor=user.email)
    return KillOut(
        etapa=resultado["etapa"],
        confirmacao=resultado["confirmacao"],
        launch=LaunchOut.model_validate(resultado["launch"]),
    )


@router.post("/launch/{launch_id}/retomar", response_model=RetomarOut)
async def retomar_launch(
    launch_id: uuid.UUID, tenant: Tenant, request: Request, user: Retomador
) -> RetomarOut:
    """§8-M10: retomada SEMPRE humana (A1 — breaker jamais se auto-retoma); incidente
    SEV1 aberto ⇒ 2 aprovadores DISTINTOS (repetir aprovador ⇒ 403, segregação §10.5).
    Retomar resolve os incidentes e reinicia a janela dos breakers."""
    servico = get_servico_lancamento(request)
    resultado = servico.retomar(tenant, launch_id, actor=user.email, aprovador_id=user.id)
    return RetomarOut(
        retomado=resultado["retomado"],
        aprovacoes=resultado["aprovacoes"],
        exigidas=resultado["exigidas"],
        launch=LaunchOut.model_validate(resultado["launch"]),
    )


@router.get("/os/{os_id}/monitor", response_model=MonitorOut)
async def monitor_da_os(
    os_id: uuid.UUID, tenant: Tenant, request: Request, _user: Autenticado
) -> MonitorOut:
    """§8-M10 (T13): todos os KPIs como par previsto×realizado — conversões, lift vs
    holdout com IC95, ROAS, custo real, receita, metas×realizado e disparos/custo por
    canal — SEMPRE contra o Previsto congelado do snapshot (§1.1.2). OS sem previsto
    congelado → 409. Leitura: qualquer autenticado (padrão GET /os/{id}/saude M1)."""
    servico = get_servico_lancamento(request)
    return MonitorOut.model_validate(servico.monitor(tenant, os_id))


@router.post("/webhooks/ens", status_code=202, response_model=IngestaoOut)
async def ingerir_ens(request: Request, tenant: Tenant) -> IngestaoOut | Response:
    """§8-M10 (ingestão): webhook ENS com ASSINATURA VERIFICADA — HMAC-sha256 do
    corpo bruto com APP_SECRET no header `X-ENS-Signature`; inválida/ausente ⇒ 401
    (a assinatura é a credencial; sem Bearer). Guarda-corpo §10.2: PII no payload ou
    contato fora de hash ⇒ 422, nada é gravado. Ingerir AVALIA os breakers dos
    launches `em_rampa` das OSs afetadas (A1/A2 — pausa/kill automáticos)."""
    corpo = await request.body()
    esperada = hmac.new(
        get_settings().app_secret.encode("utf-8"), corpo, hashlib.sha256
    ).hexdigest()
    recebida = request.headers.get(ASSINATURA_HEADER, "")
    if not recebida or not hmac.compare_digest(recebida, esperada):
        return problem_response(
            401,
            "Unauthorized",
            detail=f"Assinatura ENS ausente/inválida — header {ASSINATURA_HEADER} deve ser "
            "o HMAC-sha256 (hex) do corpo com APP_SECRET (§8-M10).",
            instance=request.url.path,
        )
    try:
        lote = LoteEnsIn.model_validate_json(corpo)
    except ValidationError as exc:
        return problem_response(
            422,
            "Unprocessable Entity",
            detail="Lote ENS fora do contrato telemetry_event (§4.1).",
            instance=request.url.path,
            extra={"errors": exc.errors(include_url=False, include_input=False)},
        )
    servico = get_servico_lancamento(request)
    resultado = servico.ingerir_telemetria(
        tenant, [e.model_dump() for e in lote.eventos], fonte="ens", actor="ens"
    )
    return IngestaoOut(recebidos=resultado["recebidos"], avaliados=resultado["avaliados"])
