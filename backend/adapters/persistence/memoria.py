"""Repositório em memória do núcleo OS/governança, esteira, intake, validação,
audiência, criativo, twin/simulador, compilador e lançamento
(M1+M2+M3+M4+M5+M6+M8+M9+M10).

Implementa as portas `RepositorioOs`, `RepositorioWorkflow`, `RepositorioIntake`,
`RepositorioValidacao`, `RepositorioAudiencia`, `RepositorioCriativo`,
`RepositorioJornada`, `RepositorioSync` e `RepositorioLancamento` na MESMA instância
(tipagem estrutural §2.1).
Escolha registrada no CHANGELOG-SDD.md (M1): os testes rodam sem docker e o DDL
Postgres (jsonb/uuid/view os_saude, etapa_workflow, hike_import_log, pedido, invocacao,
validacao_campo, os_thread, documento_portao, segmento, certificado_elegibilidade,
dc_segment_cache, criativo, jornada_versao, experimento, snapshot, aprovacao, sync_run,
resource_registry, drift_check, preflight_run, launch, telemetry_event, incidente)
permanece íntegro nas migrações (§4.1);
este adapter cobre dev/teste;
o adapter SQLAlchemy/Postgres entra quando um módulo exigir durabilidade real, sem
tocar domínio nem serviços (hexagonal §2.1).
"""

import itertools
import uuid

from domain.agentes.modelos import Invocacao
from domain.audiencia.modelos import CertificadoElegibilidade, DcSegmentCache, Segmento
from domain.campanha.modelos import OS, EventoDominio, Pendencia, SlaClock
from domain.criativo.modelos import Criativo
from domain.esteira.modelos import EtapaWorkflow, HikeImportLog
from domain.experimento.modelos import Experimento
from domain.governanca.modelos import Aprovacao, Snapshot
from domain.intake.modelos import Pedido
from domain.jornada.modelos import (
    DriftCheck,
    JornadaVersao,
    PreflightRun,
    ResourceRegistry,
    SyncRun,
)
from domain.lancamento.modelos import Incidente, Launch, TelemetryEvent
from domain.validacao.modelos import DocumentoPortao, ThreadWarRoom, ValidacaoCampo


class RepositorioOsMemoria:
    def __init__(self) -> None:
        self._os: dict[uuid.UUID, OS] = {}
        self._pendencias: dict[uuid.UUID, Pendencia] = {}
        self._clocks: dict[uuid.UUID, SlaClock] = {}
        self._etapas: dict[uuid.UUID, EtapaWorkflow] = {}
        self._hike_logs: list[HikeImportLog] = []
        self._pedidos: dict[uuid.UUID, Pedido] = {}
        self._invocacoes: list[Invocacao] = []
        self._validacoes: list[ValidacaoCampo] = []
        self._threads: dict[uuid.UUID, ThreadWarRoom] = {}
        self._documentos: list[DocumentoPortao] = []
        self._segmentos: dict[uuid.UUID, Segmento] = {}
        self._certificados: list[CertificadoElegibilidade] = []
        self._dc_cache: dict[tuple[str, str], DcSegmentCache] = {}
        self._criativos: dict[uuid.UUID, Criativo] = {}
        self._jornadas: dict[uuid.UUID, JornadaVersao] = {}
        self._experimentos: dict[uuid.UUID, Experimento] = {}
        self._snapshots: dict[uuid.UUID, Snapshot] = {}
        self._aprovacoes: dict[uuid.UUID, Aprovacao] = {}
        self._sync_runs: dict[uuid.UUID, SyncRun] = {}
        self._registros: dict[tuple[str, str, str], ResourceRegistry] = {}
        self._preflights: list[PreflightRun] = []
        self._drift_checks: dict[uuid.UUID, DriftCheck] = {}
        self._ordem_drift: list[uuid.UUID] = []
        self._launches: dict[uuid.UUID, Launch] = {}
        self._ordem_launch: list[uuid.UUID] = []
        self._telemetria: list[TelemetryEvent] = []
        self._seq_telemetria = itertools.count(1)
        self._incidentes: dict[uuid.UUID, Incidente] = {}
        self._ordem_incidente: list[uuid.UUID] = []
        self._eventos: list[EventoDominio] = []
        self._seq_evento = itertools.count(1)
        self._seq_os: dict[int, itertools.count[int]] = {}

    # --- OS ---
    def adicionar_os(self, os_: OS) -> None:
        self._os[os_.id] = os_

    def obter_os(self, tenant_id: str, os_id: uuid.UUID) -> OS | None:
        os_ = self._os.get(os_id)
        return os_ if os_ is not None and os_.tenant_id == tenant_id else None

    def obter_os_por_codigo(self, codigo: str) -> OS | None:
        return next((o for o in self._os.values() if o.codigo == codigo), None)

    def listar_os(self, tenant_id: str, limit: int, offset: int) -> list[OS]:
        do_tenant = [o for o in self._os.values() if o.tenant_id == tenant_id]
        do_tenant.sort(key=lambda o: (o.created_at, o.codigo))
        return do_tenant[offset : offset + limit]

    def salvar_os(self, os_: OS) -> None:
        self._os[os_.id] = os_

    def proximo_sequencial_os(self, ano: int) -> int:
        return next(self._seq_os.setdefault(ano, itertools.count(1)))

    # --- Pendências ---
    def adicionar_pendencia(self, pendencia: Pendencia) -> None:
        self._pendencias[pendencia.id] = pendencia

    def obter_pendencia(self, pendencia_id: uuid.UUID) -> Pendencia | None:
        return self._pendencias.get(pendencia_id)

    def listar_pendencias(self, os_id: uuid.UUID) -> list[Pendencia]:
        pendencias = [p for p in self._pendencias.values() if p.os_id == os_id]
        pendencias.sort(key=lambda p: p.numero)
        return pendencias

    def proximo_numero_pendencia(self, os_id: uuid.UUID) -> int:
        return max((p.numero for p in self.listar_pendencias(os_id)), default=0) + 1

    def salvar_pendencia(self, pendencia: Pendencia) -> None:
        self._pendencias[pendencia.id] = pendencia

    # --- SLA clocks ---
    def adicionar_sla_clock(self, clock: SlaClock) -> None:
        self._clocks[clock.id] = clock

    def listar_sla_clocks(self, os_id: uuid.UUID) -> list[SlaClock]:
        return [c for c in self._clocks.values() if c.os_id == os_id]

    def salvar_sla_clock(self, clock: SlaClock) -> None:
        self._clocks[clock.id] = clock

    # --- Etapas da esteira (etapa_workflow §4.1 — M2) ---
    def adicionar_etapa(self, etapa: EtapaWorkflow) -> None:
        self._etapas[etapa.id] = etapa

    def listar_etapas(self, os_id: uuid.UUID) -> list[EtapaWorkflow]:
        etapas = [e for e in self._etapas.values() if e.os_id == os_id]
        etapas.sort(key=lambda e: e.ordem)
        return etapas

    def salvar_etapa(self, etapa: EtapaWorkflow) -> None:
        self._etapas[etapa.id] = etapa

    # --- Log de import Hike (hike_import_log — M2) ---
    def adicionar_hike_log(self, log: HikeImportLog) -> None:
        self._hike_logs.append(log)

    def listar_hike_logs(self, tenant_id: str) -> list[HikeImportLog]:
        return [log for log in self._hike_logs if log.tenant_id == tenant_id]

    # --- Pedidos (tabela `pedido` §4.1 — M3) ---
    def adicionar_pedido(self, pedido: Pedido) -> None:
        self._pedidos[pedido.id] = pedido

    def obter_pedido(self, tenant_id: str, pedido_id: uuid.UUID) -> Pedido | None:
        pedido = self._pedidos.get(pedido_id)
        return pedido if pedido is not None and pedido.tenant_id == tenant_id else None

    def salvar_pedido(self, pedido: Pedido) -> None:
        self._pedidos[pedido.id] = pedido

    # --- Ledger via_ai (`invocacao` §4.1 — M3) ---
    def adicionar_invocacao(self, invocacao: Invocacao) -> None:
        self._invocacoes.append(invocacao)

    def listar_invocacoes(self, tenant_id: str) -> list[Invocacao]:
        return [i for i in self._invocacoes if i.tenant_id == tenant_id]

    # --- Validações campo-a-campo (`validacao_campo` — M4) ---
    def adicionar_validacao(self, validacao: ValidacaoCampo) -> None:
        self._validacoes.append(validacao)

    def listar_validacoes(self, os_id: uuid.UUID, campo: str | None = None) -> list[ValidacaoCampo]:
        return [
            v for v in self._validacoes if v.os_id == os_id and (campo is None or v.campo == campo)
        ]

    # --- Threads do War Room (`os_thread` — M4) ---
    def adicionar_thread(self, thread: ThreadWarRoom) -> None:
        self._threads[thread.id] = thread

    def listar_threads(self, os_id: uuid.UUID) -> list[ThreadWarRoom]:
        return [t for t in self._threads.values() if t.os_id == os_id]

    # --- Documentos de portão (`documento_portao` — M4) ---
    def adicionar_documento(self, documento: DocumentoPortao) -> None:
        self._documentos.append(documento)

    def listar_documentos(
        self, os_id: uuid.UUID, portao: str | None = None
    ) -> list[DocumentoPortao]:
        return [
            d
            for d in self._documentos
            if d.os_id == os_id and (portao is None or d.portao == portao)
        ]

    # --- Segmentos (`segmento` §4.1 — M5) ---
    def adicionar_segmento(self, segmento: Segmento) -> None:
        self._segmentos[segmento.id] = segmento

    def obter_segmento(self, segmento_id: uuid.UUID) -> Segmento | None:
        return self._segmentos.get(segmento_id)

    def listar_segmentos(self, os_id: uuid.UUID) -> list[Segmento]:
        return [s for s in self._segmentos.values() if s.os_id == os_id]

    def salvar_segmento(self, segmento: Segmento) -> None:
        self._segmentos[segmento.id] = segmento

    # --- Certificados (`certificado_elegibilidade` §4.1 — M5) ---
    def adicionar_certificado(self, certificado: CertificadoElegibilidade) -> None:
        self._certificados.append(certificado)

    def listar_certificados(self, os_id: uuid.UUID) -> list[CertificadoElegibilidade]:
        return [c for c in self._certificados if c.os_id == os_id]

    # --- Cache Data Cloud (`dc_segment_cache` §4.1 — M5/T5a) ---
    def salvar_dc_cache(self, entrada: DcSegmentCache) -> None:
        self._dc_cache[(entrada.tenant_id, entrada.id)] = entrada

    def obter_dc_cache(self, tenant_id: str, segmento_id: str) -> DcSegmentCache | None:
        return self._dc_cache.get((tenant_id, segmento_id))

    def listar_dc_cache(self, tenant_id: str) -> list[DcSegmentCache]:
        return [e for (tenant, _), e in self._dc_cache.items() if tenant == tenant_id]

    # --- Criativos (tabela auxiliar `criativo` — migração 0003, M6) ---
    def adicionar_criativo(self, criativo: Criativo) -> None:
        self._criativos[criativo.id] = criativo

    def obter_criativo(self, criativo_id: uuid.UUID) -> Criativo | None:
        return self._criativos.get(criativo_id)

    def listar_criativos(self, os_id: uuid.UUID) -> list[Criativo]:
        return [c for c in self._criativos.values() if c.os_id == os_id]

    def salvar_criativo(self, criativo: Criativo) -> None:
        self._criativos[criativo.id] = criativo

    # --- Twin (`jornada_versao` §4.1 — M7/M8) ---
    def adicionar_jornada(self, jornada: JornadaVersao) -> None:
        self._jornadas[jornada.id] = jornada

    def obter_jornada(self, jornada_id: uuid.UUID) -> JornadaVersao | None:
        return self._jornadas.get(jornada_id)

    def listar_jornadas(self, os_id: uuid.UUID) -> list[JornadaVersao]:
        jornadas = [j for j in self._jornadas.values() if j.os_id == os_id]
        jornadas.sort(key=lambda j: j.versao)
        return jornadas

    def salvar_jornada(self, jornada: JornadaVersao) -> None:
        self._jornadas[jornada.id] = jornada

    def proxima_versao(self, os_id: uuid.UUID) -> int:
        return max((j.versao for j in self.listar_jornadas(os_id)), default=0) + 1

    # --- Experimentos (`experimento` §4.1 — leitura p/ validação §5.3 e poder §6) ---
    def adicionar_experimento(self, experimento: Experimento) -> None:
        self._experimentos[experimento.id] = experimento

    def experimento_da_os(self, os_id: uuid.UUID) -> Experimento | None:
        da_os = [e for e in self._experimentos.values() if e.os_id == os_id]
        return da_os[-1] if da_os else None

    # --- Snapshots (`snapshot` §4.1 — M8 parte 2) ---
    def adicionar_snapshot(self, snapshot: Snapshot) -> None:
        self._snapshots[snapshot.id] = snapshot

    def obter_snapshot(self, snapshot_id: uuid.UUID) -> Snapshot | None:
        return self._snapshots.get(snapshot_id)

    def obter_snapshot_por_hash(self, hash_: str) -> Snapshot | None:
        return next((s for s in self._snapshots.values() if s.hash == hash_), None)

    def listar_snapshots(self, os_id: uuid.UUID) -> list[Snapshot]:
        snapshots = [s for s in self._snapshots.values() if s.os_id == os_id]
        snapshots.sort(key=lambda s: (s.created_at is None, s.created_at))
        return snapshots

    # --- Aprovações / link mágico (`aprovacao` §4.1 — M8 parte 2) ---
    def adicionar_aprovacao(self, aprovacao: Aprovacao) -> None:
        self._aprovacoes[aprovacao.id] = aprovacao

    def obter_aprovacao_por_token_hash(self, token_hash: str) -> Aprovacao | None:
        return next((a for a in self._aprovacoes.values() if a.token_hash == token_hash), None)

    def listar_aprovacoes(self, snapshot_id: uuid.UUID) -> list[Aprovacao]:
        return [a for a in self._aprovacoes.values() if a.snapshot_id == snapshot_id]

    def salvar_aprovacao(self, aprovacao: Aprovacao) -> None:
        self._aprovacoes[aprovacao.id] = aprovacao

    # --- Sync runs (`sync_run` §4.1 — compilador M9) ---
    def adicionar_sync_run(self, run: SyncRun) -> None:
        self._sync_runs[run.id] = run

    def obter_sync_run(self, sync_run_id: uuid.UUID) -> SyncRun | None:
        return self._sync_runs.get(sync_run_id)

    def salvar_sync_run(self, run: SyncRun) -> None:
        self._sync_runs[run.id] = run

    def listar_sync_runs(
        self, snapshot_id: uuid.UUID, ambiente: str | None = None, fase: str | None = None
    ) -> list[SyncRun]:
        runs = [
            r
            for r in self._sync_runs.values()
            if r.snapshot_id == snapshot_id
            and (ambiente is None or r.ambiente == ambiente)
            and (fase is None or r.fase == fase)
        ]
        runs.sort(key=lambda r: (r.created_at is None, r.created_at))
        return runs

    # --- Registro twin↔SFMC (`resource_registry` §4.1 — unique tenant+ambiente+key) ---
    def upsert_registro(self, registro: ResourceRegistry) -> None:
        chave = (registro.tenant_id, str(registro.ambiente), registro.external_key)
        self._registros[chave] = registro

    def obter_registro(
        self, tenant_id: str, ambiente: str, external_key: str
    ) -> ResourceRegistry | None:
        return self._registros.get((tenant_id, ambiente, external_key))

    def listar_registros(self, tenant_id: str, ambiente: str) -> list[ResourceRegistry]:
        return [
            r
            for (tenant, amb, _), r in self._registros.items()
            if tenant == tenant_id and amb == ambiente
        ]

    def remover_registro(self, tenant_id: str, ambiente: str, external_key: str) -> None:
        self._registros.pop((tenant_id, ambiente, external_key), None)

    # --- Pré-voo (`preflight_run` — migração 0007, M9 fatia 2) ---
    def adicionar_preflight(self, run: PreflightRun) -> None:
        self._preflights.append(run)

    def listar_preflights(
        self, snapshot_id: uuid.UUID, ambiente: str | None = None
    ) -> list[PreflightRun]:
        return [
            p
            for p in self._preflights
            if p.snapshot_id == snapshot_id and (ambiente is None or p.ambiente == ambiente)
        ]

    # --- drift_check (§4.1 — monitor §5.4.5, M9 fatia 2) ---
    def adicionar_drift_check(self, check: DriftCheck) -> None:
        self._drift_checks[check.id] = check
        self._ordem_drift.append(check.id)

    def obter_drift_check(self, drift_id: uuid.UUID) -> DriftCheck | None:
        return self._drift_checks.get(drift_id)

    def salvar_drift_check(self, check: DriftCheck) -> None:
        self._drift_checks[check.id] = check

    def listar_drift_checks(self, snapshot_id: uuid.UUID) -> list[DriftCheck]:
        return [
            self._drift_checks[i]
            for i in self._ordem_drift
            if self._drift_checks[i].snapshot_id == snapshot_id
        ]

    # --- launch (§4.1 — Torre de Lançamento M10) ---
    def adicionar_launch(self, launch: Launch) -> None:
        self._launches[launch.id] = launch
        self._ordem_launch.append(launch.id)

    def obter_launch(self, launch_id: uuid.UUID) -> Launch | None:
        return self._launches.get(launch_id)

    def listar_launches(self, snapshot_id: uuid.UUID) -> list[Launch]:
        return [
            self._launches[i]
            for i in self._ordem_launch
            if self._launches[i].snapshot_id == snapshot_id
        ]

    def salvar_launch(self, launch: Launch) -> None:
        self._launches[launch.id] = launch

    # --- telemetry_event (§4.1 — id bigint identity emulado) ---
    def adicionar_telemetria(self, evento: TelemetryEvent) -> None:
        evento.id = next(self._seq_telemetria)
        self._telemetria.append(evento)

    def listar_telemetria(
        self, os_id: uuid.UUID, apos_id: int | None = None
    ) -> list[TelemetryEvent]:
        return [
            e
            for e in self._telemetria
            if e.os_id == os_id and (apos_id is None or (e.id or 0) > apos_id)
        ]

    def maior_id_telemetria(self) -> int:
        return self._telemetria[-1].id or 0 if self._telemetria else 0

    # --- incidente (tabela auxiliar §4.1 nota final — migração 0008, M10) ---
    def adicionar_incidente(self, incidente: Incidente) -> None:
        self._incidentes[incidente.id] = incidente
        self._ordem_incidente.append(incidente.id)

    def listar_incidentes(
        self,
        os_id: uuid.UUID | None = None,
        launch_id: uuid.UUID | None = None,
        estado: str | None = None,
    ) -> list[Incidente]:
        return [
            self._incidentes[i]
            for i in self._ordem_incidente
            if (os_id is None or self._incidentes[i].os_id == os_id)
            and (launch_id is None or self._incidentes[i].launch_id == launch_id)
            and (estado is None or self._incidentes[i].estado == estado)
        ]

    def salvar_incidente(self, incidente: Incidente) -> None:
        self._incidentes[incidente.id] = incidente

    # --- Outbox (§2.3) ---
    def adicionar_evento(self, evento: EventoDominio) -> None:
        evento.id = next(self._seq_evento)
        self._eventos.append(evento)

    def listar_eventos(
        self, os_id: uuid.UUID | None = None, tipo: str | None = None
    ) -> list[EventoDominio]:
        return [
            e
            for e in self._eventos
            if (os_id is None or e.os_id == os_id) and (tipo is None or e.type == tipo)
        ]
