"""Adapter Postgres dos agregados (A7 partes 1 e 2) — SDD §2.1/§4.1/§10.

`RepositorioSql` implementa as MESMAS portas do repositório em memória (tipagem
estrutural §2.1) persistindo em Postgres TODOS os agregados do DDL §4.1: núcleo
OS/governança, intake, esteira, twin (`jornada_versao`), snapshot/aprovação,
audiência (segmento/certificado/dc_segment_cache), criativo, experimento,
compilador (sync_run/resource_registry/drift_check/preflight_run), lançamento
(launch/telemetry_event/incidente), otimização (proposta/aprendizado/calibração),
Ateliê (agente/skill_versao/harness_*/policy_versao), o ledger `invocacao`, o
outbox `domain_event` (§2.3) e — desde o A11 — a collection RAG `agente_evidence`
(§7.4): coluna `embedding vector(1024)` via pgvector, busca top-k por cosseno
(`cosine_distance`, índice HNSW da migração 0001), filtrada por tenant + bases.

Escolhas registradas no CHANGELOG-SDD.md (A7 partes 1 e 2):
- Engine SÍNCRONO (psycopg2): as portas de repositório são `def` síncronos; o
  `DATABASE_URL` canônico (§3.1, driver asyncpg p/ alembic/healthz) é normalizado
  aqui para `postgresql+psycopg2`.
- Escritas idempotentes: `adicionar_*`/`salvar_*` fazem UPSERT por `id` — mesma
  semântica do dict em memória e o que torna as seeds (ids uuid5 §11.4/A15)
  re-executáveis a cada boot sem duplicar linhas. Exceções por identity do banco:
  `domain_event` e `telemetry_event` (INSERT com RETURNING id).
- Ordem de inserção durável: listas cujo contrato é "o último é o corrente"
  ordenam por `created_at` (migração 0012 em segmento/experimento/aprovacao/launch
  — coluna que SÓ o banco escreve, default now()) ou pela coluna temporal já
  existente. `listar_agentes`/`listar_skills` ordenam por nome/versão (exibição).
- Seleção por config (app/main.py): `DATABASE_URL` setado no ambiente E alcançável
  (sonda 2s cacheada) → SQL; senão memória (dev sem docker segue funcionando).
"""

import re
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, Row, Select, Table, create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine.url import URL, make_url

from adapters.persistence.memoria import RepositorioOsMemoria
from adapters.persistence.tabelas import (
    tabela_agente,
    tabela_agente_evidence,
    tabela_aprendizado,
    tabela_aprovacao,
    tabela_calibracao_prior,
    tabela_certificado,
    tabela_criativo,
    tabela_dc_segment_cache,
    tabela_documento_portao,
    tabela_domain_event,
    tabela_drift_check,
    tabela_etapa_workflow,
    tabela_experimento,
    tabela_harness_case,
    tabela_harness_run,
    tabela_hike_import_log,
    tabela_incidente,
    tabela_invocacao,
    tabela_jornada_versao,
    tabela_launch,
    tabela_os,
    tabela_os_thread,
    tabela_pedido,
    tabela_pendencia,
    tabela_policy_versao,
    tabela_preflight_run,
    tabela_proposta_otimizacao,
    tabela_resource_registry,
    tabela_segmento,
    tabela_skill_versao,
    tabela_sla_clock,
    tabela_snapshot,
    tabela_sync_run,
    tabela_telemetry_event,
    tabela_validacao_campo,
)
from domain.agentes.modelos import AgenteEvidence, Invocacao
from domain.atelie.modelos import Agente, HarnessCase, HarnessRun, SkillVersao
from domain.audiencia.modelos import CertificadoElegibilidade, DcSegmentCache, Segmento
from domain.campanha.modelos import OS, EventoDominio, Pendencia, SlaClock
from domain.criativo.modelos import CelulaCriativo, Criativo
from domain.esteira.modelos import EtapaWorkflow, HikeImportLog
from domain.experimento.modelos import Experimento
from domain.governanca.modelos import Aprovacao, PolicyVersao, Snapshot
from domain.intake.modelos import Pedido
from domain.jornada.modelos import (
    DriftCheck,
    JornadaVersao,
    PreflightRun,
    ResourceRegistry,
    SyncRun,
)
from domain.lancamento.modelos import Incidente, Launch, TelemetryEvent
from domain.otimizacao.modelos import Aprendizado, CalibracaoPrior, PropostaOtimizacao
from domain.validacao.modelos import DocumentoPortao, ThreadWarRoom, ValidacaoCampo

_TIMEOUT_PROBE_S = 2


# --------------------------------------------------------------- engine/seleção
def url_sincrona(database_url: str) -> URL:
    """Normaliza o `DATABASE_URL` canônico (§3.1, `postgresql+asyncpg`) para o
    driver síncrono psycopg2 — as portas de repositório são síncronas (§2.1)."""
    return make_url(database_url).set(drivername="postgresql+psycopg2")


def criar_engine(database_url: str) -> Engine:
    return create_engine(
        url_sincrona(database_url),
        pool_pre_ping=True,  # robustez: conexões mortas são recicladas, não estouram
        connect_args={"connect_timeout": _TIMEOUT_PROBE_S},
    )


@lru_cache(maxsize=8)
def postgres_alcancavel(database_url: str) -> bool:
    """Sonda curta (timeout 2s) — cacheada por URL no processo (o compose só sobe a
    api com o db saudável; dev sem docker cai para memória uma única vez)."""
    try:
        engine = criar_engine(database_url)
        try:
            with engine.connect() as conexao:
                conexao.execute(text("select 1"))
            return True
        finally:
            engine.dispose()
    except Exception:
        return False


def criar_repositorio(database_url: str | None) -> RepositorioOsMemoria:
    """Seleção por config (A7 parte 1): `DATABASE_URL` setado E alcançável → repos
    SQL; senão memória (fallback dev sem docker). O retorno anota o tipo base — o
    chamador depende só das portas (tipagem estrutural §2.1)."""
    if database_url and postgres_alcancavel(database_url):
        return RepositorioSql(criar_engine(database_url))
    return RepositorioOsMemoria()


# ------------------------------------------------------------------- hidratação
def _linha_para_os(linha: Row[Any]) -> OS:
    return OS(
        id=linha.id,
        tenant_id=linha.tenant_id,
        codigo=linha.codigo,
        nome=linha.nome,
        tshirt=linha.tshirt,
        fase=linha.fase,
        briefing=linha.briefing,
        frozen=linha.frozen,
        created_by=linha.created_by,
        created_at=linha.created_at,
        updated_at=linha.updated_at,
    )


def _linha_para_pendencia(linha: Row[Any]) -> Pendencia:
    return Pendencia(
        id=linha.id,
        os_id=linha.os_id,
        numero=linha.numero,
        tipo=linha.tipo,
        titulo=linha.titulo,
        descricao=linha.descricao,
        severidade=linha.severidade,
        bloqueante=bool(linha.bloqueante),
        bloqueia_etapa=linha.bloqueia_etapa,
        status=linha.status,
        accountable=linha.accountable,
        aceite=linha.aceite,
        origem=linha.origem,
        via_ai=bool(linha.via_ai),
        created_at=linha.created_at,
    )


def _linha_para_sla_clock(linha: Row[Any]) -> SlaClock:
    return SlaClock(
        id=linha.id,
        os_id=linha.os_id,
        etapa=linha.etapa,
        prazo=linha.prazo,
        estado=linha.estado,
        pausas=linha.pausas or [],
    )


def _linha_para_pedido(linha: Row[Any]) -> Pedido:
    return Pedido(
        id=linha.id,
        tenant_id=linha.tenant_id,
        solicitante=linha.solicitante,
        conteudo=linha.conteudo,
        completude=float(linha.completude or 0),
        faltantes=list(linha.faltantes or []),
        estado=linha.estado,
        os_id=linha.os_id,
        created_at=linha.created_at,
        updated_at=linha.updated_at,
    )


def _linha_para_etapa(linha: Row[Any]) -> EtapaWorkflow:
    return EtapaWorkflow(
        id=linha.id,
        os_id=linha.os_id,
        ordem=linha.ordem,
        nome=linha.nome,
        responsavel=linha.responsavel,
        sla_dias=linha.sla_dias,
        estado=linha.estado,
        checklist=linha.checklist or [],
        dependencias=linha.dependencias or [],
        hike_ref=linha.hike_ref,
    )


def _linha_para_hike_log(linha: Row[Any]) -> HikeImportLog:
    return HikeImportLog(
        id=linha.id,
        tenant_id=linha.tenant_id,
        os_id=linha.os_id,
        hike_card_id=linha.hike_card_id,
        status=linha.status,
        detalhe=linha.detalhe,
        created_at=linha.created_at,
    )


def _linha_para_validacao(linha: Row[Any]) -> ValidacaoCampo:
    return ValidacaoCampo(
        id=linha.id,
        os_id=linha.os_id,
        campo=linha.campo,
        veredito=linha.veredito,
        checagens=linha.checagens or [],
        evidencia=linha.evidencia or {},
        created_at=linha.created_at,
        por=linha.por,
        atualizado_em=linha.atualizado_em,
    )


def _linha_para_thread(linha: Row[Any]) -> ThreadWarRoom:
    return ThreadWarRoom(
        id=linha.id,
        os_id=linha.os_id,
        campo=linha.campo,
        titulo=linha.titulo,
        mensagens=linha.mensagens or [],
        status=linha.status,
        created_at=linha.created_at,
    )


def _linha_para_documento(linha: Row[Any]) -> DocumentoPortao:
    return DocumentoPortao(
        id=linha.id,
        os_id=linha.os_id,
        portao=linha.portao,
        nome_arquivo=linha.nome_arquivo,
        conteudo=bytes(linha.conteudo),  # psycopg2 devolve memoryview
        hash=linha.hash,
        created_at=linha.created_at,
    )


def _linha_para_evento(linha: Row[Any]) -> EventoDominio:
    return EventoDominio(
        tenant_id=linha.tenant_id,
        type=linha.type,
        payload=linha.payload or {},
        actor=linha.actor,
        via_ai=bool(linha.via_ai),
        created_at=linha.created_at,
        os_id=linha.os_id,
        id=linha.id,
    )


# ----------------------------------------------------- hidratação (A7 parte 2)
def _num(valor: Any) -> float | None:
    """numeric → float (psycopg2 devolve Decimal)."""
    return float(valor) if valor is not None else None


def _celula_para_json(celula: CelulaCriativo) -> dict[str, Any]:
    """Célula da matriz → item do jsonb `celulas` (formato da migração 0003)."""
    return {
        "canal": celula.canal,
        "variante": celula.variante,
        "conteudo": celula.conteudo,
        "estado": celula.estado,
        "aprovada_por": str(celula.aprovada_por) if celula.aprovada_por else None,
        "aprovada_em": celula.aprovada_em.isoformat() if celula.aprovada_em else None,
        "observacao": celula.observacao,
    }


def _celula_de_json(dado: dict[str, Any]) -> CelulaCriativo:
    aprovada_por = dado.get("aprovada_por")
    aprovada_em = dado.get("aprovada_em")
    return CelulaCriativo(
        canal=dado["canal"],
        variante=dado["variante"],
        conteudo=dado.get("conteudo") or {},
        estado=dado.get("estado") or "gerado",
        aprovada_por=uuid.UUID(aprovada_por) if aprovada_por else None,
        aprovada_em=datetime.fromisoformat(aprovada_em) if aprovada_em else None,
        observacao=dado.get("observacao"),
    )


def _linha_para_jornada(linha: Row[Any]) -> JornadaVersao:
    return JornadaVersao(
        id=linha.id,
        os_id=linha.os_id,
        versao=linha.versao,
        grafo=linha.grafo or {},
        hash=linha.hash,
        estado=linha.estado,
        premissas=list(linha.premissas or []),
        custo_projetado=_num(linha.custo_projetado),
        simulacao=linha.simulacao,
        previsto=linha.previsto,
        created_at=linha.created_at,
    )


def _linha_para_snapshot(linha: Row[Any]) -> Snapshot:
    return Snapshot(
        id=linha.id,
        os_id=linha.os_id,
        hash=linha.hash,
        conteudo=linha.conteudo or {},
        previsto=linha.previsto,
        created_at=linha.created_at,
    )


def _linha_para_aprovacao(linha: Row[Any]) -> Aprovacao:
    return Aprovacao(
        id=linha.id,
        snapshot_id=linha.snapshot_id,
        token_hash=linha.token_hash,
        expira_em=linha.expira_em,
        alcada=linha.alcada,
        decisao=linha.decisao,
        decidido_em=linha.decidido_em,
        decidido_meta=linha.decidido_meta,
        ressalvas=list(linha.ressalvas or []),
        invalidada_em=linha.invalidada_em,
        invalidada_motivo=linha.invalidada_motivo,
    )


def _linha_para_segmento(linha: Row[Any]) -> Segmento:
    return Segmento(
        id=linha.id,
        os_id=linha.os_id,
        origem=linha.origem,
        dc_segment_id=linha.dc_segment_id,
        sql_publico=linha.sql_publico,
        criterios_resumo=linha.criterios_resumo,
        contagem_bruta=linha.contagem_bruta,
        contagem_liquida=linha.contagem_liquida,
        waterfall=list(linha.waterfall or []),
        volume_abordagem=dict(linha.volume_abordagem or {}),
        holdout_pct=float(linha.holdout_pct) if linha.holdout_pct is not None else 10.0,
        frescor=dict(linha.frescor or {}),
    )


def _linha_para_certificado(linha: Row[Any]) -> CertificadoElegibilidade:
    return CertificadoElegibilidade(
        id=linha.id,
        os_id=linha.os_id,
        hash=linha.hash,
        suprimidos=dict(linha.suprimidos or {}),
        liquido=linha.liquido,
        emitido_em=linha.emitido_em,
        valido_ate=linha.valido_ate,
        last_mile=linha.last_mile,
    )


def _linha_para_dc_cache(linha: Row[Any]) -> DcSegmentCache:
    return DcSegmentCache(
        id=linha.id,
        tenant_id=linha.tenant_id,
        nome=linha.nome,
        criterios_resumo=linha.criterios_resumo,
        membros=linha.membros,
        dmos=list(linha.dmos or []),
        republicado_em=linha.republicado_em,
        ciclo=linha.ciclo,
        status=linha.status,
        atualizado_em=linha.atualizado_em,
    )


def _linha_para_criativo(linha: Row[Any]) -> Criativo:
    return Criativo(
        id=linha.id,
        os_id=linha.os_id,
        kv_master=dict(linha.kv_master or {}),
        kv_master_ref=linha.kv_master_ref,
        celulas=[_celula_de_json(c) for c in (linha.celulas or [])],
        created_at=linha.created_at,
        updated_at=linha.updated_at,
    )


def _linha_para_experimento(linha: Row[Any]) -> Experimento:
    return Experimento(
        id=linha.id,
        os_id=linha.os_id,
        holdout_pct=float(linha.holdout_pct),
        n_minimo=linha.n_minimo,
        mde_pp=float(linha.mde_pp),
        janela_dias=linha.janela_dias,
        metricas=dict(linha.metricas or {}),
        travado_em=linha.travado_em,
        estado=linha.estado,
        resultado=linha.resultado,
    )


def _linha_para_sync_run(linha: Row[Any]) -> SyncRun:
    return SyncRun(
        id=linha.id,
        snapshot_id=linha.snapshot_id,
        ambiente=linha.ambiente,
        fase=linha.fase,
        plano=list(linha.plano) if linha.plano is not None else None,
        resultado=linha.resultado,
        estado=linha.estado,
        api_calls=int(linha.api_calls or 0),
        created_at=linha.created_at,
    )


def _linha_para_registro(linha: Row[Any]) -> ResourceRegistry:
    return ResourceRegistry(
        id=linha.id,
        tenant_id=linha.tenant_id,
        no_jgc=linha.no_jgc,
        tipo_sfmc=linha.tipo_sfmc,
        external_key=linha.external_key,
        sfmc_id=linha.sfmc_id,
        ambiente=linha.ambiente,
        snapshot_hash=linha.snapshot_hash,
    )


def _linha_para_drift(linha: Row[Any]) -> DriftCheck:
    return DriftCheck(
        id=linha.id,
        snapshot_id=linha.snapshot_id,
        recurso=linha.recurso,
        estado=linha.estado,
        diff=dict(linha.diff or {}),
        resolucao=linha.resolucao,
        checked_at=linha.checked_at,
    )


def _linha_para_preflight(linha: Row[Any]) -> PreflightRun:
    return PreflightRun(
        id=linha.id,
        snapshot_id=linha.snapshot_id,
        ambiente=linha.ambiente,
        resultado=linha.resultado,
        itens=list(linha.itens or []),
        created_at=linha.created_at,
    )


def _linha_para_launch(linha: Row[Any]) -> Launch:
    return Launch(
        id=linha.id,
        snapshot_id=linha.snapshot_id,
        ondas=list(linha.ondas or []),
        onda_atual=int(linha.onda_atual or 0),
        estado=linha.estado,
        breakers=dict(linha.breakers or {}),
        eventos=list(linha.eventos or []),
    )


def _linha_para_telemetria(linha: Row[Any]) -> TelemetryEvent:
    return TelemetryEvent(
        tenant_id=linha.tenant_id,
        tipo=linha.tipo,
        ts=linha.ts,
        os_id=linha.os_id,
        no_jgc=linha.no_jgc,
        canal=linha.canal,
        contato_hash=linha.contato_hash,
        fonte=linha.fonte,
        payload=linha.payload,
        id=linha.id,
    )


def _linha_para_incidente(linha: Row[Any]) -> Incidente:
    return Incidente(
        id=linha.id,
        os_id=linha.os_id,
        launch_id=linha.launch_id,
        sev=linha.sev,
        tipo=linha.tipo,
        titulo=linha.titulo,
        estado=linha.estado,
        descricao=linha.descricao,
        meta=dict(linha.meta or {}),
        aberto_em=linha.aberto_em,
        resolvido_em=linha.resolvido_em,
    )


def _linha_para_proposta(linha: Row[Any]) -> PropostaOtimizacao:
    return PropostaOtimizacao(
        id=linha.id,
        os_id=linha.os_id,
        jornada_base_id=linha.jornada_base_id,
        titulo=linha.titulo,
        motivacao=linha.motivacao or "",
        grafo_proposto=dict(linha.grafo_proposto or {}),
        diff=dict(linha.diff or {}),
        impacto=dict(linha.impacto or {}),
        esforco=linha.esforco,
        risco=float(linha.risco),
        score=float(linha.score) if linha.score is not None else 0.0,
        estado=linha.estado,
        motivo_rejeicao=linha.motivo_rejeicao,
        jornada_gerada_id=linha.jornada_gerada_id,
        via_ai=bool(linha.via_ai),
        decidido_por=linha.decidido_por,
        decidido_em=linha.decidido_em,
        created_at=linha.created_at,
    )


def _linha_para_aprendizado(linha: Row[Any]) -> Aprendizado:
    return Aprendizado(
        id=linha.id,
        tenant_id=linha.tenant_id,
        os_id=linha.os_id,
        origem=linha.origem,
        status=linha.status,
        texto=linha.texto,
        meta=dict(linha.meta or {}),
        herdado_de=linha.herdado_de,
        created_at=linha.created_at,
    )


def _linha_para_calibracao(linha: Row[Any]) -> CalibracaoPrior:
    return CalibracaoPrior(
        id=linha.id,
        tenant_id=linha.tenant_id,
        tipo_campanha=linha.tipo_campanha,
        versao=int(linha.versao or 0),
        priors=dict(linha.priors or {}),
        score=_num(linha.score),
        backtest=linha.backtest,
        publicada_em=linha.publicada_em,
    )


def _linha_para_agente(linha: Row[Any]) -> Agente:
    return Agente(
        id=linha.id,
        tenant_id=linha.tenant_id,
        nome=linha.nome,
        camada=linha.camada,
        etapa_workflow=linha.etapa_workflow,
        modelo_perfil=linha.modelo_perfil,
        deterministico=bool(linha.deterministico),
    )


def _linha_para_skill(linha: Row[Any]) -> SkillVersao:
    return SkillVersao(
        id=linha.id,
        agente_id=linha.agente_id,
        versao=linha.versao,
        skill_md=linha.skill_md,
        execution_profile=dict(linha.execution_profile or {}),
        bases_rag=list(linha.bases_rag or []),
        estado=linha.estado,
        harness_score=_num(linha.harness_score),
        publicada_em=linha.publicada_em,
    )


def _linha_para_harness_case(linha: Row[Any]) -> HarnessCase:
    return HarnessCase(
        id=linha.id,
        agente_id=linha.agente_id,
        input=dict(linha.input or {}),
        esperado=dict(linha.esperado or {}),
        dimensoes=list(linha.dimensoes or []),
    )


def _linha_para_harness_run(linha: Row[Any]) -> HarnessRun:
    return HarnessRun(
        id=linha.id,
        skill_versao_id=linha.skill_versao_id,
        resultados=dict(linha.resultados or {}),
        score=_num(linha.score),
        passou=bool(linha.passou) if linha.passou is not None else None,
        created_at=linha.created_at,
    )


def _linha_para_invocacao(linha: Row[Any]) -> Invocacao:
    return Invocacao(
        id=linha.id,
        tenant_id=linha.tenant_id,
        os_id=linha.os_id,
        agente_id=linha.agente_id,
        skill_versao=linha.skill_versao,
        usuario_portador=linha.usuario_portador,
        input=linha.input,
        output=linha.output,
        evidencias=list(linha.evidencias or []),
        judge=linha.judge,
        aceito_por=linha.aceito_por,
        aceito_em=linha.aceito_em,
        tokens=linha.tokens,
        latencia_ms=linha.latencia_ms,
        created_at=linha.created_at,
    )


def _linha_para_evidencia(linha: Row[Any]) -> AgenteEvidence:
    """pgvector devolve numpy.ndarray — normaliza para list[float] (dataclass §4.1)."""
    embedding = linha.embedding
    return AgenteEvidence(
        id=linha.id,
        tenant_id=linha.tenant_id,
        base=linha.base,
        ref=linha.ref,
        chunk=linha.chunk,
        meta=dict(linha.meta or {}),
        embedding=[float(v) for v in embedding] if embedding is not None else None,
    )


def _linha_para_policy(linha: Row[Any]) -> PolicyVersao:
    return PolicyVersao(
        id=linha.id,
        tenant_id=linha.tenant_id,
        versao=linha.versao,
        conteudo=dict(linha.conteudo or {}),
        estado=linha.estado,
        publicada_em=linha.publicada_em,
    )


# ------------------------------------------------------------------ repositório
class RepositorioSql(RepositorioOsMemoria):
    """Persistência Postgres dos agregados core; herda o fallback em memória para
    os agregados ainda não migrados (parte 2) — a MESMA instância implementa todas
    as portas, como o repositório em memória (tipagem estrutural §2.1)."""

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine

    # --- infra ---
    def _upsert(
        self,
        tabela: Table,
        valores: dict[str, Any],
        *,
        conflito: tuple[str, ...] = ("id",),
    ) -> None:
        """UPSERT restrito às colunas FORNECIDAS: colunas fora de `valores` (ex.:
        `created_at` de ordenação — migração 0012) ficam com o default do banco no
        insert e são PRESERVADAS no update (nunca entram no set_)."""
        stmt = pg_insert(tabela).values(**valores)
        pos_conflito = {
            nome: stmt.excluded[nome] for nome in valores if not tabela.c[nome].primary_key
        }
        with self._engine.begin() as conexao:
            conexao.execute(
                stmt.on_conflict_do_update(index_elements=list(conflito), set_=pos_conflito)
            )

    def _todas(self, consulta: Select[Any]) -> list[Row[Any]]:
        with self._engine.connect() as conexao:
            return list(conexao.execute(consulta).all())

    def _primeira(self, consulta: Select[Any]) -> Row[Any] | None:
        linhas = self._todas(consulta.limit(1))
        return linhas[0] if linhas else None

    # --- OS ---
    def adicionar_os(self, os_: OS) -> None:
        self._upsert(
            tabela_os,
            {
                "id": os_.id,
                "tenant_id": os_.tenant_id,
                "codigo": os_.codigo,
                "nome": os_.nome,
                "tshirt": os_.tshirt,
                "fase": os_.fase,
                "briefing": os_.briefing,
                "frozen": os_.frozen,
                "created_by": os_.created_by,
                "created_at": os_.created_at,
                "updated_at": os_.updated_at,
            },
        )

    def obter_os(self, tenant_id: str, os_id: uuid.UUID) -> OS | None:
        linha = self._primeira(
            select(tabela_os).where(tabela_os.c.id == os_id, tabela_os.c.tenant_id == tenant_id)
        )
        return _linha_para_os(linha) if linha is not None else None

    def obter_os_por_codigo(self, codigo: str, tenant_id: str | None = None) -> OS | None:
        """Achado 22/UAT5: `codigo` é unique POR TENANT (migração 0014) — informe o
        tenant e a busca fica escopada. `tenant_id=None` = busca GLOBAL, reservada aos
        chamadores legitimamente cross-tenant (o loader de extracts §8-M10, que confere
        o tenant da OS logo depois)."""
        consulta = select(tabela_os).where(tabela_os.c.codigo == codigo)
        if tenant_id is not None:
            consulta = consulta.where(tabela_os.c.tenant_id == tenant_id)
        linha = self._primeira(consulta)
        return _linha_para_os(linha) if linha is not None else None

    def obter_os_por_id(self, os_id: uuid.UUID) -> OS | None:
        """Sem escopo de tenant — só o link mágico usa (C03: o token é a credencial e
        o tenant sai da OS dona do snapshot). Ver RepositorioAprovacao."""
        linha = self._primeira(select(tabela_os).where(tabela_os.c.id == os_id))
        return _linha_para_os(linha) if linha is not None else None

    def listar_os(self, tenant_id: str, limit: int, offset: int) -> list[OS]:
        consulta = (
            select(tabela_os)
            .where(tabela_os.c.tenant_id == tenant_id)
            .order_by(tabela_os.c.created_at, tabela_os.c.codigo)
            .limit(limit)
            .offset(offset)
        )
        return [_linha_para_os(linha) for linha in self._todas(consulta)]

    def salvar_os(self, os_: OS) -> None:
        self.adicionar_os(os_)  # upsert por id — mesma semântica do dict em memória

    def proximo_sequencial_os(self, ano: int, tenant_id: str | None = None) -> int:
        """max+1 dos códigos `OS-{ano}-NNNN` existentes — sobrevive a restart (o
        contador em memória zerava; CodigoDuplicado §8-M1 segue protegendo).

        Achado 22/UAT5: o max+1 é POR TENANT quando o tenant é informado — o número da
        OS não pode contar o volume de TODOS os clientes (vazamento de negócio)."""
        consulta = select(tabela_os.c.codigo).where(tabela_os.c.codigo.like(f"OS-{ano}-%"))
        if tenant_id is not None:
            consulta = consulta.where(tabela_os.c.tenant_id == tenant_id)
        padrao = re.compile(rf"OS-{ano}-(\d+)$")
        sequenciais = [
            int(m.group(1))
            for linha in self._todas(consulta)
            if (m := padrao.fullmatch(linha.codigo)) is not None
        ]
        return max(sequenciais, default=0) + 1

    # --- Pendências ---
    def adicionar_pendencia(self, pendencia: Pendencia) -> None:
        self._upsert(
            tabela_pendencia,
            {
                "id": pendencia.id,
                "os_id": pendencia.os_id,
                "numero": pendencia.numero,
                "tipo": pendencia.tipo,
                "titulo": pendencia.titulo,
                "descricao": pendencia.descricao,
                "severidade": pendencia.severidade,
                "bloqueante": pendencia.bloqueante,
                "bloqueia_etapa": pendencia.bloqueia_etapa,
                "status": pendencia.status,
                "accountable": pendencia.accountable,
                "aceite": pendencia.aceite,
                "origem": pendencia.origem,
                "via_ai": pendencia.via_ai,
                "created_at": pendencia.created_at,
            },
        )

    def obter_pendencia(self, pendencia_id: uuid.UUID) -> Pendencia | None:
        linha = self._primeira(
            select(tabela_pendencia).where(tabela_pendencia.c.id == pendencia_id)
        )
        return _linha_para_pendencia(linha) if linha is not None else None

    def listar_pendencias(self, os_id: uuid.UUID) -> list[Pendencia]:
        consulta = (
            select(tabela_pendencia)
            .where(tabela_pendencia.c.os_id == os_id)
            .order_by(tabela_pendencia.c.numero)
        )
        return [_linha_para_pendencia(linha) for linha in self._todas(consulta)]

    def proximo_numero_pendencia(self, os_id: uuid.UUID) -> int:
        consulta = select(func.max(tabela_pendencia.c.numero)).where(
            tabela_pendencia.c.os_id == os_id
        )
        linha = self._primeira(consulta)
        maior = linha[0] if linha is not None else None
        return (maior or 0) + 1

    def salvar_pendencia(self, pendencia: Pendencia) -> None:
        self.adicionar_pendencia(pendencia)

    # --- SLA clocks ---
    def adicionar_sla_clock(self, clock: SlaClock) -> None:
        self._upsert(
            tabela_sla_clock,
            {
                "id": clock.id,
                "os_id": clock.os_id,
                "etapa": clock.etapa,
                "prazo": clock.prazo,
                "estado": clock.estado,
                "pausas": clock.pausas,
            },
        )

    def listar_sla_clocks(self, os_id: uuid.UUID) -> list[SlaClock]:
        consulta = select(tabela_sla_clock).where(tabela_sla_clock.c.os_id == os_id)
        return [_linha_para_sla_clock(linha) for linha in self._todas(consulta)]

    def salvar_sla_clock(self, clock: SlaClock) -> None:
        self.adicionar_sla_clock(clock)

    # --- Validações campo-a-campo (`validacao_campo` — M4) ---
    def adicionar_validacao(self, validacao: ValidacaoCampo) -> None:
        """Upsert por id: revalidar o mesmo campo atualiza a linha vigente (emenda B01 —
        o índice unique (os_id, campo) da migração 0013 sustenta a invariante no banco)."""
        self._upsert(
            tabela_validacao_campo,
            {
                "id": validacao.id,
                "os_id": validacao.os_id,
                "campo": validacao.campo,
                "veredito": validacao.veredito,
                "checagens": validacao.checagens,
                "evidencia": validacao.evidencia,
                "created_at": validacao.created_at,
                "por": validacao.por,
                "atualizado_em": validacao.atualizado_em,
            },
        )

    def listar_validacoes(self, os_id: uuid.UUID, campo: str | None = None) -> list[ValidacaoCampo]:
        consulta = select(tabela_validacao_campo).where(tabela_validacao_campo.c.os_id == os_id)
        if campo is not None:
            consulta = consulta.where(tabela_validacao_campo.c.campo == campo)
        consulta = consulta.order_by(tabela_validacao_campo.c.created_at)
        return [_linha_para_validacao(linha) for linha in self._todas(consulta)]

    # --- Threads do War Room (`os_thread` — M4) ---
    def adicionar_thread(self, thread: ThreadWarRoom) -> None:
        self._upsert(
            tabela_os_thread,
            {
                "id": thread.id,
                "os_id": thread.os_id,
                "campo": thread.campo,
                "titulo": thread.titulo,
                "mensagens": thread.mensagens,
                "status": thread.status,
                "created_at": thread.created_at,
            },
        )

    def listar_threads(self, os_id: uuid.UUID) -> list[ThreadWarRoom]:
        consulta = (
            select(tabela_os_thread)
            .where(tabela_os_thread.c.os_id == os_id)
            .order_by(tabela_os_thread.c.created_at)
        )
        return [_linha_para_thread(linha) for linha in self._todas(consulta)]

    # --- Documentos de portão (`documento_portao` — M4) ---
    def adicionar_documento(self, documento: DocumentoPortao) -> None:
        self._upsert(
            tabela_documento_portao,
            {
                "id": documento.id,
                "os_id": documento.os_id,
                "portao": documento.portao,
                "nome_arquivo": documento.nome_arquivo,
                "conteudo": documento.conteudo,
                "hash": documento.hash,
                "created_at": documento.created_at,
            },
        )

    def listar_documentos(
        self, os_id: uuid.UUID, portao: str | None = None
    ) -> list[DocumentoPortao]:
        consulta = select(tabela_documento_portao).where(tabela_documento_portao.c.os_id == os_id)
        if portao is not None:
            consulta = consulta.where(tabela_documento_portao.c.portao == portao)
        consulta = consulta.order_by(tabela_documento_portao.c.created_at)
        return [_linha_para_documento(linha) for linha in self._todas(consulta)]

    # --- Pedidos (`pedido` — M3) ---
    def adicionar_pedido(self, pedido: Pedido) -> None:
        self._upsert(
            tabela_pedido,
            {
                "id": pedido.id,
                "tenant_id": pedido.tenant_id,
                "solicitante": pedido.solicitante,
                "conteudo": pedido.conteudo,
                "completude": pedido.completude,
                "faltantes": pedido.faltantes,
                "estado": pedido.estado,
                "os_id": pedido.os_id,
                "created_at": pedido.created_at,
                "updated_at": pedido.updated_at,
            },
        )

    def obter_pedido(self, tenant_id: str, pedido_id: uuid.UUID) -> Pedido | None:
        linha = self._primeira(
            select(tabela_pedido).where(
                tabela_pedido.c.id == pedido_id, tabela_pedido.c.tenant_id == tenant_id
            )
        )
        return _linha_para_pedido(linha) if linha is not None else None

    def listar_pedidos(self, tenant_id: str) -> list[Pedido]:
        # mais recente primeiro (fila de trabalho) — mesma regra do repositório em memória
        recencia = func.coalesce(tabela_pedido.c.updated_at, tabela_pedido.c.created_at)
        consulta = (
            select(tabela_pedido)
            .where(tabela_pedido.c.tenant_id == tenant_id)
            .order_by(recencia.desc().nullslast())
        )
        return [_linha_para_pedido(linha) for linha in self._todas(consulta)]

    def salvar_pedido(self, pedido: Pedido) -> None:
        self.adicionar_pedido(pedido)

    # --- Etapas da esteira (`etapa_workflow` — M2) ---
    def adicionar_etapa(self, etapa: EtapaWorkflow) -> None:
        self._upsert(
            tabela_etapa_workflow,
            {
                "id": etapa.id,
                "os_id": etapa.os_id,
                "ordem": etapa.ordem,
                "nome": etapa.nome,
                "responsavel": etapa.responsavel,
                "sla_dias": etapa.sla_dias,
                "estado": etapa.estado,
                "checklist": etapa.checklist,
                "dependencias": etapa.dependencias,
                "hike_ref": etapa.hike_ref,
            },
        )

    def listar_etapas(self, os_id: uuid.UUID) -> list[EtapaWorkflow]:
        consulta = (
            select(tabela_etapa_workflow)
            .where(tabela_etapa_workflow.c.os_id == os_id)
            .order_by(tabela_etapa_workflow.c.ordem)
        )
        return [_linha_para_etapa(linha) for linha in self._todas(consulta)]

    def salvar_etapa(self, etapa: EtapaWorkflow) -> None:
        self.adicionar_etapa(etapa)

    # --- Log de import Hike (`hike_import_log` — M2) ---
    def adicionar_hike_log(self, log: HikeImportLog) -> None:
        self._upsert(
            tabela_hike_import_log,
            {
                "id": log.id,
                "tenant_id": log.tenant_id,
                "os_id": log.os_id,
                "hike_card_id": log.hike_card_id,
                "status": log.status,
                "detalhe": log.detalhe,
                "created_at": log.created_at,
            },
        )

    def listar_hike_logs(self, tenant_id: str) -> list[HikeImportLog]:
        consulta = (
            select(tabela_hike_import_log)
            .where(tabela_hike_import_log.c.tenant_id == tenant_id)
            .order_by(tabela_hike_import_log.c.created_at)
        )
        return [_linha_para_hike_log(linha) for linha in self._todas(consulta)]

    # --- Outbox (`domain_event` §2.3) ---
    def adicionar_evento(self, evento: EventoDominio) -> None:
        stmt = (
            pg_insert(tabela_domain_event)
            .values(
                tenant_id=evento.tenant_id,
                os_id=evento.os_id,
                type=evento.type,
                payload=evento.payload,
                actor=evento.actor,
                via_ai=evento.via_ai,
                created_at=evento.created_at,
            )
            .returning(tabela_domain_event.c.id)
        )
        with self._engine.begin() as conexao:
            evento.id = conexao.execute(stmt).scalar_one()

    def listar_eventos(
        self, os_id: uuid.UUID | None = None, tipo: str | None = None
    ) -> list[EventoDominio]:
        consulta = select(tabela_domain_event)
        if os_id is not None:
            consulta = consulta.where(tabela_domain_event.c.os_id == os_id)
        if tipo is not None:
            consulta = consulta.where(tabela_domain_event.c.type == tipo)
        consulta = consulta.order_by(tabela_domain_event.c.id)
        return [_linha_para_evento(linha) for linha in self._todas(consulta)]

    # ================================================================ A7 parte 2
    # --- Twin (`jornada_versao` §4.1 — M7/M8) ---
    def adicionar_jornada(self, jornada: JornadaVersao) -> None:
        self._upsert(
            tabela_jornada_versao,
            {
                "id": jornada.id,
                "os_id": jornada.os_id,
                "versao": jornada.versao,
                "grafo": jornada.grafo,
                "hash": jornada.hash,
                "estado": jornada.estado,
                "premissas": jornada.premissas,
                "custo_projetado": jornada.custo_projetado,
                "simulacao": jornada.simulacao,
                "previsto": jornada.previsto,
                "created_at": jornada.created_at,
            },
        )

    def obter_jornada(self, jornada_id: uuid.UUID) -> JornadaVersao | None:
        linha = self._primeira(
            select(tabela_jornada_versao).where(tabela_jornada_versao.c.id == jornada_id)
        )
        return _linha_para_jornada(linha) if linha is not None else None

    def listar_jornadas(self, os_id: uuid.UUID) -> list[JornadaVersao]:
        consulta = (
            select(tabela_jornada_versao)
            .where(tabela_jornada_versao.c.os_id == os_id)
            .order_by(tabela_jornada_versao.c.versao)
        )
        return [_linha_para_jornada(linha) for linha in self._todas(consulta)]

    def salvar_jornada(self, jornada: JornadaVersao) -> None:
        self.adicionar_jornada(jornada)

    def proxima_versao(self, os_id: uuid.UUID) -> int:
        linha = self._primeira(
            select(func.max(tabela_jornada_versao.c.versao)).where(
                tabela_jornada_versao.c.os_id == os_id
            )
        )
        maior = linha[0] if linha is not None else None
        return (maior or 0) + 1

    # --- Experimentos (`experimento` §4.1) ---
    def adicionar_experimento(self, experimento: Experimento) -> None:
        self._upsert(
            tabela_experimento,
            {
                "id": experimento.id,
                "os_id": experimento.os_id,
                "holdout_pct": experimento.holdout_pct,
                "n_minimo": experimento.n_minimo,
                "mde_pp": experimento.mde_pp,
                "janela_dias": experimento.janela_dias,
                "metricas": experimento.metricas,
                "travado_em": experimento.travado_em,
                "estado": experimento.estado,
                "resultado": experimento.resultado,
            },
        )

    def experimento_da_os(self, os_id: uuid.UUID) -> Experimento | None:
        # "o último é o corrente": ordem de inserção durável (created_at migração 0012)
        consulta = (
            select(tabela_experimento)
            .where(tabela_experimento.c.os_id == os_id)
            .order_by(tabela_experimento.c.created_at.desc(), tabela_experimento.c.id.desc())
        )
        linha = self._primeira(consulta)
        return _linha_para_experimento(linha) if linha is not None else None

    def obter_experimento(self, experimento_id: uuid.UUID) -> Experimento | None:
        linha = self._primeira(
            select(tabela_experimento).where(tabela_experimento.c.id == experimento_id)
        )
        return _linha_para_experimento(linha) if linha is not None else None

    def salvar_experimento(self, experimento: Experimento) -> None:
        self.adicionar_experimento(experimento)

    # --- Snapshots (`snapshot` §4.1 — M8 parte 2) ---
    def adicionar_snapshot(self, snapshot: Snapshot) -> None:
        self._upsert(
            tabela_snapshot,
            {
                "id": snapshot.id,
                "os_id": snapshot.os_id,
                "hash": snapshot.hash,
                "conteudo": snapshot.conteudo,
                "previsto": snapshot.previsto,
                "created_at": snapshot.created_at,
            },
        )

    def obter_snapshot(self, snapshot_id: uuid.UUID) -> Snapshot | None:
        linha = self._primeira(select(tabela_snapshot).where(tabela_snapshot.c.id == snapshot_id))
        return _linha_para_snapshot(linha) if linha is not None else None

    def obter_snapshot_por_hash(self, hash_: str) -> Snapshot | None:
        linha = self._primeira(select(tabela_snapshot).where(tabela_snapshot.c.hash == hash_))
        return _linha_para_snapshot(linha) if linha is not None else None

    def listar_snapshots(self, os_id: uuid.UUID) -> list[Snapshot]:
        consulta = (
            select(tabela_snapshot)
            .where(tabela_snapshot.c.os_id == os_id)
            .order_by(tabela_snapshot.c.created_at.asc().nulls_last(), tabela_snapshot.c.id)
        )
        return [_linha_para_snapshot(linha) for linha in self._todas(consulta)]

    # --- Aprovações / link mágico (`aprovacao` §4.1 — M8 parte 2) ---
    def adicionar_aprovacao(self, aprovacao: Aprovacao) -> None:
        self._upsert(
            tabela_aprovacao,
            {
                "id": aprovacao.id,
                "snapshot_id": aprovacao.snapshot_id,
                "token_hash": aprovacao.token_hash,
                "expira_em": aprovacao.expira_em,
                "alcada": aprovacao.alcada,
                "decisao": aprovacao.decisao,
                "decidido_em": aprovacao.decidido_em,
                "decidido_meta": aprovacao.decidido_meta,
                "ressalvas": aprovacao.ressalvas,
                "invalidada_em": aprovacao.invalidada_em,
                "invalidada_motivo": aprovacao.invalidada_motivo,
            },
        )

    def obter_aprovacao_por_token_hash(self, token_hash: str) -> Aprovacao | None:
        linha = self._primeira(
            select(tabela_aprovacao).where(tabela_aprovacao.c.token_hash == token_hash)
        )
        return _linha_para_aprovacao(linha) if linha is not None else None

    def listar_aprovacoes(self, snapshot_id: uuid.UUID) -> list[Aprovacao]:
        consulta = (
            select(tabela_aprovacao)
            .where(tabela_aprovacao.c.snapshot_id == snapshot_id)
            .order_by(tabela_aprovacao.c.created_at.asc().nulls_last(), tabela_aprovacao.c.id)
        )
        return [_linha_para_aprovacao(linha) for linha in self._todas(consulta)]

    def salvar_aprovacao(self, aprovacao: Aprovacao) -> None:
        self.adicionar_aprovacao(aprovacao)

    # --- Segmentos (`segmento` §4.1 — M5) ---
    def adicionar_segmento(self, segmento: Segmento) -> None:
        self._upsert(
            tabela_segmento,
            {
                "id": segmento.id,
                "os_id": segmento.os_id,
                "origem": segmento.origem,
                "dc_segment_id": segmento.dc_segment_id,
                "sql_publico": segmento.sql_publico,
                "criterios_resumo": segmento.criterios_resumo,
                "contagem_bruta": segmento.contagem_bruta,
                "contagem_liquida": segmento.contagem_liquida,
                "waterfall": segmento.waterfall,
                "volume_abordagem": segmento.volume_abordagem,
                "holdout_pct": segmento.holdout_pct,
                "frescor": segmento.frescor,
            },
        )

    def obter_segmento(self, segmento_id: uuid.UUID) -> Segmento | None:
        linha = self._primeira(select(tabela_segmento).where(tabela_segmento.c.id == segmento_id))
        return _linha_para_segmento(linha) if linha is not None else None

    def listar_segmentos(self, os_id: uuid.UUID) -> list[Segmento]:
        # ordem de inserção durável (created_at migração 0012): o último é o corrente
        consulta = (
            select(tabela_segmento)
            .where(tabela_segmento.c.os_id == os_id)
            .order_by(tabela_segmento.c.created_at.asc().nulls_last(), tabela_segmento.c.id)
        )
        return [_linha_para_segmento(linha) for linha in self._todas(consulta)]

    def salvar_segmento(self, segmento: Segmento) -> None:
        self.adicionar_segmento(segmento)

    # --- Certificados (`certificado_elegibilidade` §4.1 — M5) ---
    def adicionar_certificado(self, certificado: CertificadoElegibilidade) -> None:
        self._upsert(
            tabela_certificado,
            {
                "id": certificado.id,
                "os_id": certificado.os_id,
                "hash": certificado.hash,
                "suprimidos": certificado.suprimidos,
                "liquido": certificado.liquido,
                "emitido_em": certificado.emitido_em,
                "valido_ate": certificado.valido_ate,
                "last_mile": certificado.last_mile,
            },
        )

    def listar_certificados(self, os_id: uuid.UUID) -> list[CertificadoElegibilidade]:
        consulta = (
            select(tabela_certificado)
            .where(tabela_certificado.c.os_id == os_id)
            .order_by(tabela_certificado.c.emitido_em.asc().nulls_last(), tabela_certificado.c.id)
        )
        return [_linha_para_certificado(linha) for linha in self._todas(consulta)]

    def salvar_certificado(self, certificado: CertificadoElegibilidade) -> None:
        self.adicionar_certificado(certificado)

    # --- Cache Data Cloud (`dc_segment_cache` §4.1 — M5/T5a) ---
    def salvar_dc_cache(self, entrada: DcSegmentCache) -> None:
        self._upsert(
            tabela_dc_segment_cache,
            {
                "id": entrada.id,
                "tenant_id": entrada.tenant_id,
                "nome": entrada.nome,
                "criterios_resumo": entrada.criterios_resumo,
                "membros": entrada.membros,
                "dmos": entrada.dmos,
                "republicado_em": entrada.republicado_em,
                "ciclo": entrada.ciclo,
                "status": entrada.status,
                "atualizado_em": entrada.atualizado_em,
            },
        )

    def obter_dc_cache(self, tenant_id: str, segmento_id: str) -> DcSegmentCache | None:
        linha = self._primeira(
            select(tabela_dc_segment_cache).where(
                tabela_dc_segment_cache.c.id == segmento_id,
                tabela_dc_segment_cache.c.tenant_id == tenant_id,
            )
        )
        return _linha_para_dc_cache(linha) if linha is not None else None

    def listar_dc_cache(self, tenant_id: str) -> list[DcSegmentCache]:
        consulta = (
            select(tabela_dc_segment_cache)
            .where(tabela_dc_segment_cache.c.tenant_id == tenant_id)
            .order_by(tabela_dc_segment_cache.c.id)
        )
        return [_linha_para_dc_cache(linha) for linha in self._todas(consulta)]

    # --- Criativos (tabela auxiliar `criativo` — migração 0003, M6) ---
    def adicionar_criativo(self, criativo: Criativo) -> None:
        self._upsert(
            tabela_criativo,
            {
                "id": criativo.id,
                "os_id": criativo.os_id,
                "kv_master": criativo.kv_master,
                "kv_master_ref": criativo.kv_master_ref,
                "celulas": [_celula_para_json(c) for c in criativo.celulas],
                "created_at": criativo.created_at,
                "updated_at": criativo.updated_at,
            },
        )

    def obter_criativo(self, criativo_id: uuid.UUID) -> Criativo | None:
        linha = self._primeira(select(tabela_criativo).where(tabela_criativo.c.id == criativo_id))
        return _linha_para_criativo(linha) if linha is not None else None

    def listar_criativos(self, os_id: uuid.UUID) -> list[Criativo]:
        consulta = (
            select(tabela_criativo)
            .where(tabela_criativo.c.os_id == os_id)
            .order_by(tabela_criativo.c.created_at.asc().nulls_last(), tabela_criativo.c.id)
        )
        return [_linha_para_criativo(linha) for linha in self._todas(consulta)]

    def salvar_criativo(self, criativo: Criativo) -> None:
        self.adicionar_criativo(criativo)

    # --- Sync runs (`sync_run` §4.1 — compilador M9) ---
    def adicionar_sync_run(self, run: SyncRun) -> None:
        self._upsert(
            tabela_sync_run,
            {
                "id": run.id,
                "snapshot_id": run.snapshot_id,
                "ambiente": run.ambiente,
                "fase": run.fase,
                "plano": run.plano,
                "resultado": run.resultado,
                "estado": run.estado,
                "api_calls": run.api_calls,
                "created_at": run.created_at,
            },
        )

    def obter_sync_run(self, sync_run_id: uuid.UUID) -> SyncRun | None:
        linha = self._primeira(select(tabela_sync_run).where(tabela_sync_run.c.id == sync_run_id))
        return _linha_para_sync_run(linha) if linha is not None else None

    def salvar_sync_run(self, run: SyncRun) -> None:
        self.adicionar_sync_run(run)

    def listar_sync_runs(
        self, snapshot_id: uuid.UUID, ambiente: str | None = None, fase: str | None = None
    ) -> list[SyncRun]:
        consulta = select(tabela_sync_run).where(tabela_sync_run.c.snapshot_id == snapshot_id)
        if ambiente is not None:
            consulta = consulta.where(tabela_sync_run.c.ambiente == ambiente)
        if fase is not None:
            consulta = consulta.where(tabela_sync_run.c.fase == fase)
        consulta = consulta.order_by(
            tabela_sync_run.c.created_at.asc().nulls_last(), tabela_sync_run.c.id
        )
        return [_linha_para_sync_run(linha) for linha in self._todas(consulta)]

    # --- Registro twin↔SFMC (`resource_registry` §4.1) ---
    def upsert_registro(self, registro: ResourceRegistry) -> None:
        # conflito na unique(tenant_id, ambiente, external_key) — id original preservado
        self._upsert(
            tabela_resource_registry,
            {
                "id": registro.id,
                "tenant_id": registro.tenant_id,
                "no_jgc": registro.no_jgc,
                "tipo_sfmc": registro.tipo_sfmc,
                "external_key": registro.external_key,
                "sfmc_id": registro.sfmc_id,
                "ambiente": registro.ambiente,
                "snapshot_hash": registro.snapshot_hash,
            },
            conflito=("tenant_id", "ambiente", "external_key"),
        )

    def obter_registro(
        self, tenant_id: str, ambiente: str, external_key: str
    ) -> ResourceRegistry | None:
        linha = self._primeira(
            select(tabela_resource_registry).where(
                tabela_resource_registry.c.tenant_id == tenant_id,
                tabela_resource_registry.c.ambiente == ambiente,
                tabela_resource_registry.c.external_key == external_key,
            )
        )
        return _linha_para_registro(linha) if linha is not None else None

    def listar_registros(self, tenant_id: str, ambiente: str) -> list[ResourceRegistry]:
        consulta = (
            select(tabela_resource_registry)
            .where(
                tabela_resource_registry.c.tenant_id == tenant_id,
                tabela_resource_registry.c.ambiente == ambiente,
            )
            .order_by(tabela_resource_registry.c.external_key)
        )
        return [_linha_para_registro(linha) for linha in self._todas(consulta)]

    def remover_registro(self, tenant_id: str, ambiente: str, external_key: str) -> None:
        with self._engine.begin() as conexao:
            conexao.execute(
                tabela_resource_registry.delete().where(
                    tabela_resource_registry.c.tenant_id == tenant_id,
                    tabela_resource_registry.c.ambiente == ambiente,
                    tabela_resource_registry.c.external_key == external_key,
                )
            )

    # --- Pré-voo (`preflight_run` — migração 0007, M9 fatia 2) ---
    def adicionar_preflight(self, run: PreflightRun) -> None:
        self._upsert(
            tabela_preflight_run,
            {
                "id": run.id,
                "snapshot_id": run.snapshot_id,
                "ambiente": run.ambiente,
                "resultado": run.resultado,
                "itens": run.itens,
                "created_at": run.created_at,
            },
        )

    def listar_preflights(
        self, snapshot_id: uuid.UUID, ambiente: str | None = None
    ) -> list[PreflightRun]:
        consulta = select(tabela_preflight_run).where(
            tabela_preflight_run.c.snapshot_id == snapshot_id
        )
        if ambiente is not None:
            consulta = consulta.where(tabela_preflight_run.c.ambiente == ambiente)
        consulta = consulta.order_by(
            tabela_preflight_run.c.created_at.asc().nulls_last(), tabela_preflight_run.c.id
        )
        return [_linha_para_preflight(linha) for linha in self._todas(consulta)]

    # --- drift_check (§4.1 — monitor §5.4.5, M9 fatia 2) ---
    def adicionar_drift_check(self, check: DriftCheck) -> None:
        valores: dict[str, Any] = {
            "id": check.id,
            "snapshot_id": check.snapshot_id,
            "recurso": check.recurso,
            "estado": check.estado,
            "diff": check.diff,
            "resolucao": check.resolucao,
        }
        if check.checked_at is not None:  # None → default now() do banco
            valores["checked_at"] = check.checked_at
        self._upsert(tabela_drift_check, valores)

    def obter_drift_check(self, drift_id: uuid.UUID) -> DriftCheck | None:
        linha = self._primeira(
            select(tabela_drift_check).where(tabela_drift_check.c.id == drift_id)
        )
        return _linha_para_drift(linha) if linha is not None else None

    def salvar_drift_check(self, check: DriftCheck) -> None:
        self.adicionar_drift_check(check)

    def listar_drift_checks(self, snapshot_id: uuid.UUID) -> list[DriftCheck]:
        consulta = (
            select(tabela_drift_check)
            .where(tabela_drift_check.c.snapshot_id == snapshot_id)
            .order_by(tabela_drift_check.c.checked_at.asc().nulls_last(), tabela_drift_check.c.id)
        )
        return [_linha_para_drift(linha) for linha in self._todas(consulta)]

    # --- launch (§4.1 — Torre de Lançamento M10) ---
    def adicionar_launch(self, launch: Launch) -> None:
        self._upsert(
            tabela_launch,
            {
                "id": launch.id,
                "snapshot_id": launch.snapshot_id,
                "ondas": launch.ondas,
                "onda_atual": launch.onda_atual,
                "estado": launch.estado,
                "breakers": launch.breakers,
                "eventos": launch.eventos,
            },
        )

    def obter_launch(self, launch_id: uuid.UUID) -> Launch | None:
        linha = self._primeira(select(tabela_launch).where(tabela_launch.c.id == launch_id))
        return _linha_para_launch(linha) if linha is not None else None

    def listar_launches(self, snapshot_id: uuid.UUID) -> list[Launch]:
        # ordem de inserção durável (created_at migração 0012): o último é o corrente
        consulta = (
            select(tabela_launch)
            .where(tabela_launch.c.snapshot_id == snapshot_id)
            .order_by(tabela_launch.c.created_at.asc().nulls_last(), tabela_launch.c.id)
        )
        return [_linha_para_launch(linha) for linha in self._todas(consulta)]

    def salvar_launch(self, launch: Launch) -> None:
        self.adicionar_launch(launch)

    # --- telemetry_event (§4.1 — id bigint identity do banco) ---
    def adicionar_telemetria(self, evento: TelemetryEvent) -> None:
        stmt = (
            pg_insert(tabela_telemetry_event)
            .values(
                tenant_id=evento.tenant_id,
                os_id=evento.os_id,
                no_jgc=evento.no_jgc,
                canal=evento.canal,
                tipo=evento.tipo,
                contato_hash=evento.contato_hash,
                fonte=evento.fonte,
                ts=evento.ts,
                payload=evento.payload,
            )
            .returning(tabela_telemetry_event.c.id)
        )
        with self._engine.begin() as conexao:
            evento.id = conexao.execute(stmt).scalar_one()

    def listar_telemetria(
        self, os_id: uuid.UUID, apos_id: int | None = None
    ) -> list[TelemetryEvent]:
        consulta = select(tabela_telemetry_event).where(tabela_telemetry_event.c.os_id == os_id)
        if apos_id is not None:
            consulta = consulta.where(tabela_telemetry_event.c.id > apos_id)
        consulta = consulta.order_by(tabela_telemetry_event.c.id)
        return [_linha_para_telemetria(linha) for linha in self._todas(consulta)]

    def maior_id_telemetria(self) -> int:
        linha = self._primeira(select(func.max(tabela_telemetry_event.c.id)))
        maior = linha[0] if linha is not None else None
        return int(maior or 0)

    # --- incidente (tabela auxiliar §4.1 nota final — migração 0008, M10) ---
    def adicionar_incidente(self, incidente: Incidente) -> None:
        valores: dict[str, Any] = {
            "id": incidente.id,
            "os_id": incidente.os_id,
            "launch_id": incidente.launch_id,
            "sev": incidente.sev,
            "tipo": incidente.tipo,
            "titulo": incidente.titulo,
            "descricao": incidente.descricao,
            "estado": incidente.estado,
            "meta": incidente.meta,
            "resolvido_em": incidente.resolvido_em,
        }
        if incidente.aberto_em is not None:  # None → default now() do banco
            valores["aberto_em"] = incidente.aberto_em
        self._upsert(tabela_incidente, valores)

    def listar_incidentes(
        self,
        os_id: uuid.UUID | None = None,
        launch_id: uuid.UUID | None = None,
        estado: str | None = None,
    ) -> list[Incidente]:
        consulta = select(tabela_incidente)
        if os_id is not None:
            consulta = consulta.where(tabela_incidente.c.os_id == os_id)
        if launch_id is not None:
            consulta = consulta.where(tabela_incidente.c.launch_id == launch_id)
        if estado is not None:
            consulta = consulta.where(tabela_incidente.c.estado == estado)
        consulta = consulta.order_by(
            tabela_incidente.c.aberto_em.asc().nulls_last(), tabela_incidente.c.id
        )
        return [_linha_para_incidente(linha) for linha in self._todas(consulta)]

    def salvar_incidente(self, incidente: Incidente) -> None:
        self.adicionar_incidente(incidente)

    # --- Propostas do optimize (`proposta_otimizacao` — migração 0009, M11) ---
    def adicionar_proposta(self, proposta: PropostaOtimizacao) -> None:
        self._upsert(
            tabela_proposta_otimizacao,
            {
                "id": proposta.id,
                "os_id": proposta.os_id,
                "jornada_base_id": proposta.jornada_base_id,
                "titulo": proposta.titulo,
                "motivacao": proposta.motivacao,
                "grafo_proposto": proposta.grafo_proposto,
                "diff": proposta.diff,
                "impacto": proposta.impacto,
                "esforco": proposta.esforco,
                "risco": proposta.risco,
                "score": proposta.score,
                "estado": proposta.estado,
                "motivo_rejeicao": proposta.motivo_rejeicao,
                "jornada_gerada_id": proposta.jornada_gerada_id,
                "via_ai": proposta.via_ai,
                "decidido_por": proposta.decidido_por,
                "decidido_em": proposta.decidido_em,
                "created_at": proposta.created_at,
            },
        )

    def obter_proposta(self, proposta_id: uuid.UUID) -> PropostaOtimizacao | None:
        linha = self._primeira(
            select(tabela_proposta_otimizacao).where(tabela_proposta_otimizacao.c.id == proposta_id)
        )
        return _linha_para_proposta(linha) if linha is not None else None

    def listar_propostas(
        self, os_id: uuid.UUID, estado: str | None = None
    ) -> list[PropostaOtimizacao]:
        consulta = select(tabela_proposta_otimizacao).where(
            tabela_proposta_otimizacao.c.os_id == os_id
        )
        if estado is not None:
            consulta = consulta.where(tabela_proposta_otimizacao.c.estado == estado)
        consulta = consulta.order_by(
            tabela_proposta_otimizacao.c.created_at.asc().nulls_last(),
            tabela_proposta_otimizacao.c.id,
        )
        return [_linha_para_proposta(linha) for linha in self._todas(consulta)]

    def salvar_proposta(self, proposta: PropostaOtimizacao) -> None:
        self.adicionar_proposta(proposta)

    # --- Aprendizados (`aprendizado` — migração 0009, M11) ---
    def adicionar_aprendizado(self, aprendizado: Aprendizado) -> None:
        self._upsert(
            tabela_aprendizado,
            {
                "id": aprendizado.id,
                "tenant_id": aprendizado.tenant_id,
                "os_id": aprendizado.os_id,
                "origem": aprendizado.origem,
                "status": aprendizado.status,
                "texto": aprendizado.texto,
                "meta": aprendizado.meta,
                "herdado_de": aprendizado.herdado_de,
                "created_at": aprendizado.created_at,
            },
        )

    def listar_aprendizados(
        self, os_id: uuid.UUID | None = None, status: str | None = None
    ) -> list[Aprendizado]:
        consulta = select(tabela_aprendizado)
        if os_id is not None:
            consulta = consulta.where(tabela_aprendizado.c.os_id == os_id)
        if status is not None:
            consulta = consulta.where(tabela_aprendizado.c.status == status)
        consulta = consulta.order_by(
            tabela_aprendizado.c.created_at.asc().nulls_last(), tabela_aprendizado.c.id
        )
        return [_linha_para_aprendizado(linha) for linha in self._todas(consulta)]

    # --- Priors versionados (`calibracao_prior` §4.1 — M11) ---
    def adicionar_calibracao(self, calibracao: CalibracaoPrior) -> None:
        self._upsert(
            tabela_calibracao_prior,
            {
                "id": calibracao.id,
                "tenant_id": calibracao.tenant_id,
                "tipo_campanha": calibracao.tipo_campanha,
                "versao": calibracao.versao,
                "priors": calibracao.priors,
                "score": calibracao.score,
                "backtest": calibracao.backtest,
                "publicada_em": calibracao.publicada_em,
            },
        )

    def listar_calibracoes(
        self, tenant_id: str, tipo_campanha: str | None = None
    ) -> list[CalibracaoPrior]:
        consulta = select(tabela_calibracao_prior).where(
            tabela_calibracao_prior.c.tenant_id == tenant_id
        )
        if tipo_campanha is not None:
            consulta = consulta.where(
                (tabela_calibracao_prior.c.tipo_campanha.is_(None))
                | (tabela_calibracao_prior.c.tipo_campanha == tipo_campanha)
            )
        consulta = consulta.order_by(
            tabela_calibracao_prior.c.versao.asc().nulls_first(), tabela_calibracao_prior.c.id
        )
        return [_linha_para_calibracao(linha) for linha in self._todas(consulta)]

    # --- Ateliê (`agente`/`skill_versao`/`harness_*` §4.1 — M12) ---
    def adicionar_agente(self, agente: Agente) -> None:
        self._upsert(
            tabela_agente,
            {
                "id": agente.id,
                "tenant_id": agente.tenant_id,
                "nome": agente.nome,
                "camada": agente.camada,
                "etapa_workflow": agente.etapa_workflow,
                "modelo_perfil": agente.modelo_perfil,
                "deterministico": agente.deterministico,
            },
        )

    def obter_agente(self, tenant_id: str, agente_id: uuid.UUID) -> Agente | None:
        linha = self._primeira(
            select(tabela_agente).where(
                tabela_agente.c.id == agente_id, tabela_agente.c.tenant_id == tenant_id
            )
        )
        return _linha_para_agente(linha) if linha is not None else None

    def obter_agente_por_nome(self, nome: str) -> Agente | None:
        """`agente.nome` é unique GLOBAL (§4.1)."""
        linha = self._primeira(select(tabela_agente).where(tabela_agente.c.nome == nome))
        return _linha_para_agente(linha) if linha is not None else None

    def listar_agentes(self, tenant_id: str) -> list[Agente]:
        consulta = (
            select(tabela_agente)
            .where(tabela_agente.c.tenant_id == tenant_id)
            .order_by(tabela_agente.c.nome)
        )
        return [_linha_para_agente(linha) for linha in self._todas(consulta)]

    def adicionar_skill(self, skill: SkillVersao) -> None:
        self._upsert(
            tabela_skill_versao,
            {
                "id": skill.id,
                "agente_id": skill.agente_id,
                "versao": skill.versao,
                "skill_md": skill.skill_md,
                "execution_profile": skill.execution_profile,
                "bases_rag": skill.bases_rag,
                "estado": skill.estado,
                "harness_score": skill.harness_score,
                "publicada_em": skill.publicada_em,
            },
        )

    def obter_skill(self, skill_id: uuid.UUID) -> SkillVersao | None:
        linha = self._primeira(
            select(tabela_skill_versao).where(tabela_skill_versao.c.id == skill_id)
        )
        return _linha_para_skill(linha) if linha is not None else None

    def listar_skills(self, agente_id: uuid.UUID) -> list[SkillVersao]:
        consulta = (
            select(tabela_skill_versao)
            .where(tabela_skill_versao.c.agente_id == agente_id)
            .order_by(tabela_skill_versao.c.versao, tabela_skill_versao.c.id)
        )
        return [_linha_para_skill(linha) for linha in self._todas(consulta)]

    def salvar_skill(self, skill: SkillVersao) -> None:
        self.adicionar_skill(skill)

    def versoes_skills_publicadas(self) -> dict[str, str]:
        """Última publicada por agente (publicada_em) — mesma regra da memória."""
        consulta = (
            select(
                tabela_agente.c.nome,
                tabela_skill_versao.c.versao,
            )
            .select_from(
                tabela_skill_versao.join(
                    tabela_agente, tabela_skill_versao.c.agente_id == tabela_agente.c.id
                )
            )
            .where(
                tabela_skill_versao.c.estado == "publicada",
                tabela_skill_versao.c.publicada_em.is_not(None),
            )
            .order_by(tabela_skill_versao.c.publicada_em, tabela_skill_versao.c.id)
        )
        versoes: dict[str, str] = {}
        for linha in self._todas(consulta):  # a última (maior publicada_em) prevalece
            versoes[linha.nome] = linha.versao
        return versoes

    def adicionar_harness_case(self, caso: HarnessCase) -> None:
        self._upsert(
            tabela_harness_case,
            {
                "id": caso.id,
                "agente_id": caso.agente_id,
                "input": caso.input,
                "esperado": caso.esperado,
                "dimensoes": caso.dimensoes,
            },
        )

    def listar_harness_cases(self, agente_id: uuid.UUID) -> list[HarnessCase]:
        consulta = (
            select(tabela_harness_case)
            .where(tabela_harness_case.c.agente_id == agente_id)
            .order_by(tabela_harness_case.c.id)
        )
        return [_linha_para_harness_case(linha) for linha in self._todas(consulta)]

    def adicionar_harness_run(self, run: HarnessRun) -> None:
        self._upsert(
            tabela_harness_run,
            {
                "id": run.id,
                "skill_versao_id": run.skill_versao_id,
                "resultados": run.resultados,
                "score": run.score,
                "passou": run.passou,
                "created_at": run.created_at,
            },
        )

    def listar_harness_runs(self, skill_versao_id: uuid.UUID) -> list[HarnessRun]:
        consulta = (
            select(tabela_harness_run)
            .where(tabela_harness_run.c.skill_versao_id == skill_versao_id)
            .order_by(tabela_harness_run.c.created_at.asc().nulls_last(), tabela_harness_run.c.id)
        )
        return [_linha_para_harness_run(linha) for linha in self._todas(consulta)]

    # --- Policy-as-code (`policy_versao` §4.1 — M12 parte 2) ---
    def adicionar_policy(self, policy: PolicyVersao) -> None:
        self._upsert(
            tabela_policy_versao,
            {
                "id": policy.id,
                "tenant_id": policy.tenant_id,
                "versao": policy.versao,
                "conteudo": policy.conteudo,
                "estado": policy.estado,
                "publicada_em": policy.publicada_em,
            },
        )

    def obter_policy(self, tenant_id: str, policy_id: uuid.UUID) -> PolicyVersao | None:
        linha = self._primeira(
            select(tabela_policy_versao).where(
                tabela_policy_versao.c.id == policy_id,
                tabela_policy_versao.c.tenant_id == tenant_id,
            )
        )
        return _linha_para_policy(linha) if linha is not None else None

    def listar_policies(self, tenant_id: str) -> list[PolicyVersao]:
        consulta = (
            select(tabela_policy_versao)
            .where(tabela_policy_versao.c.tenant_id == tenant_id)
            .order_by(tabela_policy_versao.c.versao, tabela_policy_versao.c.id)
        )
        return [_linha_para_policy(linha) for linha in self._todas(consulta)]

    def salvar_policy(self, policy: PolicyVersao) -> None:
        self.adicionar_policy(policy)

    def politica_publicada_atual(self, tenant_id: str | None = None) -> PolicyVersao | None:
        consulta = select(tabela_policy_versao).where(tabela_policy_versao.c.estado == "publicada")
        if tenant_id is not None:
            consulta = consulta.where(tabela_policy_versao.c.tenant_id == tenant_id)
        consulta = consulta.order_by(tabela_policy_versao.c.versao.desc())
        linha = self._primeira(consulta)
        return _linha_para_policy(linha) if linha is not None else None

    # --- RAG (`agente_evidence` §4.1/§7.4 — A11: pgvector cosine + HNSW) ---
    def adicionar_evidencia(self, evidencia: AgenteEvidence) -> None:
        """Com vetor → Postgres (coluna `vector(1024)` NOT NULL). Sem vetor (M11
        promove aprendizado em caminho determinístico §10.6, que NUNCA depende do
        hub) → fallback em memória herdado, até o `rag reindex`/re-promoção — a
        apuração jamais quebra por causa do RAG."""
        if evidencia.embedding is None:
            super().adicionar_evidencia(evidencia)
            return
        self._upsert(
            tabela_agente_evidence,
            {
                "id": evidencia.id,
                "tenant_id": evidencia.tenant_id,
                "base": evidencia.base,
                "ref": evidencia.ref,
                "chunk": evidencia.chunk,
                "meta": evidencia.meta,
                "embedding": evidencia.embedding,
            },
        )

    def listar_evidencias(self, tenant_id: str, base: str) -> list[AgenteEvidence]:
        """Banco + fallback em memória (linhas sem vetor do processo atual)."""
        consulta = (
            select(tabela_agente_evidence)
            .where(
                tabela_agente_evidence.c.tenant_id == tenant_id,
                tabela_agente_evidence.c.base == base,
            )
            .order_by(tabela_agente_evidence.c.ref.asc().nulls_last(), tabela_agente_evidence.c.id)
        )
        do_banco = [_linha_para_evidencia(linha) for linha in self._todas(consulta)]
        return do_banco + super().listar_evidencias(tenant_id, base)

    def buscar_evidencias(
        self, tenant_id: str, bases: list[str], embedding: list[float], k: int
    ) -> list[AgenteEvidence]:
        """Top-k por cosseno no banco (`vector_cosine_ops`, índice HNSW da migração
        0001), filtrado por tenant + bases autorizadas (§7.3/§7.4)."""
        if not bases or k <= 0:
            return []
        consulta = (
            select(tabela_agente_evidence)
            .where(
                tabela_agente_evidence.c.tenant_id == tenant_id,
                tabela_agente_evidence.c.base.in_(list(bases)),
            )
            .order_by(tabela_agente_evidence.c.embedding.cosine_distance(embedding))
            .limit(k)
        )
        return [_linha_para_evidencia(linha) for linha in self._todas(consulta)]

    # --- Ledger via_ai (`invocacao` §4.1 — M3/LGPD Art. 20) ---
    def adicionar_invocacao(self, invocacao: Invocacao) -> None:
        self._upsert(
            tabela_invocacao,
            {
                "id": invocacao.id,
                "tenant_id": invocacao.tenant_id,
                "os_id": invocacao.os_id,
                "agente_id": invocacao.agente_id,
                "skill_versao": invocacao.skill_versao,
                "usuario_portador": invocacao.usuario_portador,
                "input": invocacao.input,
                "output": invocacao.output,
                "evidencias": invocacao.evidencias,
                "judge": invocacao.judge,
                "aceito_por": invocacao.aceito_por,
                "aceito_em": invocacao.aceito_em,
                "tokens": invocacao.tokens,
                "latencia_ms": invocacao.latencia_ms,
                "created_at": invocacao.created_at,
            },
        )

    def listar_invocacoes(self, tenant_id: str) -> list[Invocacao]:
        consulta = (
            select(tabela_invocacao)
            .where(tabela_invocacao.c.tenant_id == tenant_id)
            .order_by(tabela_invocacao.c.created_at.asc().nulls_last(), tabela_invocacao.c.id)
        )
        return [_linha_para_invocacao(linha) for linha in self._todas(consulta)]

    def obter_invocacao(self, invocacao_id: uuid.UUID) -> Invocacao | None:
        linha = self._primeira(
            select(tabela_invocacao).where(tabela_invocacao.c.id == invocacao_id)
        )
        return _linha_para_invocacao(linha) if linha is not None else None
