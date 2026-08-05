"""Caso de uso do M9 (fatia 2) · Monitor de drift twin ↔ SFMC (SDD §5.4.5, §8-M9) —
DETERMINÍSTICO, **LLM PROIBIDO em todo este caminho** (§5.4/§10.6).

- `verificar` (GET /drift — job on-demand; o job de 30min do §5.4.5 reusa este mesmo
  caso de uso): para cada `resource_registry` do tenant/ambiente, retrieve do estado
  real via SFMCPort → decompila → compara por hash/campos (domain/jornada/drift.py,
  código puro) → grava `drift_check` (§4.1). Qualquer drift emite `drift.detected`
  (§2.3); **drift em PROD abre pendência automática BLOQUEANTE** na OS (A4) — dedupe
  por origem `drift:prod` (não reabre enquanto houver uma aberta).
- `resolver` (POST /drift/{id}/resolver): adopt | enforce | excecao (§8-M9); `excecao`
  EXIGE prazo. Decisão registrada em `drift_check.resolucao` (+ meta auditável no
  `diff.resolucao_meta`); quando não resta drift pendente no ambiente, a pendência
  automática é resolvida (evento `pendencia.resolved` via ServicoOs).
  `enforce` não re-aplica aqui: o caminho de reconvergência é o próprio plan/apply
  idempotente (§5.4.1-2) — re-plan marca `alterar` e o apply recria o recurso.
"""

import uuid
from datetime import datetime
from typing import Any

from application.ports.clock import ClockPort
from application.ports.repositorio_sync import RepositorioSync
from application.ports.sfmc import SFMCPort
from application.services.compilador_service import _OPERACOES
from application.services.os_service import ServicoOs
from domain.campanha.erros import NaoEncontrado
from domain.campanha.modelos import OS, EventoDominio
from domain.governanca.modelos import Snapshot
from domain.jornada import drift as regras_drift
from domain.jornada.compilador import compilar_recursos
from domain.jornada.erros import DriftJaResolvido, ExcecaoSemPrazo
from domain.jornada.modelos import AMBIENTES_SYNC, DriftCheck, ResourceRegistry

ORIGEM_PENDENCIA_DRIFT = "drift:prod"  # dedupe da pendência automática (A4)


class ServicoDrift:
    def __init__(
        self,
        repositorio: RepositorioSync,
        sfmc: SFMCPort,
        relogio: ClockPort,
        servico_os: ServicoOs,
    ) -> None:
        self._repo = repositorio
        self._sfmc = sfmc
        self._relogio = relogio
        self._servico_os = servico_os

    # ------------------------------------------------- GET /drift (job on-demand §5.4.5)
    async def verificar(
        self,
        tenant_id: str,
        *,
        ambiente: str | None = None,
        os_id: uuid.UUID | None = None,
        actor: str,
    ) -> list[DriftCheck]:
        """Retrieve estado real → decompila → compara hash/campos → grava drift_check."""
        checks: list[DriftCheck] = []
        ambientes = [ambiente] if ambiente else list(AMBIENTES_SYNC)
        for amb in ambientes:
            por_snapshot: dict[str, list[ResourceRegistry]] = {}
            for registro in self._repo.listar_registros(tenant_id, amb):
                if registro.snapshot_hash:
                    por_snapshot.setdefault(registro.snapshot_hash, []).append(registro)
            for hash_snapshot in sorted(por_snapshot):
                snapshot = self._repo.obter_snapshot_por_hash(hash_snapshot)
                os_ = (
                    self._repo.obter_os(tenant_id, snapshot.os_id) if snapshot is not None else None
                )
                if snapshot is None or os_ is None:
                    continue  # registro de outro tenant/snapshot desconhecido: fora do escopo
                if os_id is not None and os_.id != os_id:
                    continue
                checks.extend(
                    await self._verificar_snapshot(
                        os_, snapshot, amb, por_snapshot[hash_snapshot], actor
                    )
                )
        return checks

    # ------------------------------------------------- POST /drift/{id}/resolver (§8-M9)
    def resolver(
        self,
        tenant_id: str,
        drift_id: uuid.UUID,
        *,
        resolucao: str,
        justificativa: str | None,
        prazo_ate: datetime | None,
        actor: str,
    ) -> DriftCheck:
        check, os_ = self._drift_da_os(tenant_id, drift_id)
        if check.estado == "em_sincronia":
            raise DriftJaResolvido(
                f"Drift check {drift_id} está `em_sincronia` — nada a resolver (§4.1)."
            )
        if check.resolucao is not None:
            raise DriftJaResolvido(
                f"Drift check {drift_id} já resolvido ({check.resolucao!r}) — §4.1."
            )
        if resolucao == "excecao" and prazo_ate is None:
            raise ExcecaoSemPrazo(
                "Resolução `excecao` exige prazo (`prazo_ate`) — §8-M9: exceção com prazo."
            )
        agora = self._relogio.agora()
        check.resolucao = resolucao
        meta: dict[str, Any] = {"por": actor, "em": agora.isoformat()}
        if justificativa:
            meta["justificativa"] = justificativa.strip()
        if prazo_ate is not None:
            meta["prazo_ate"] = prazo_ate.isoformat()
        check.diff = dict(check.diff) | {"resolucao_meta": meta}
        self._repo.salvar_drift_check(check)
        self._evento(
            os_,
            "drift.resolved",
            {
                "drift_check_id": str(check.id),
                "recurso": check.recurso,
                "resolucao": resolucao,
                "ambiente": check.diff.get("ambiente"),
            },
            actor,
        )
        ambiente = str(check.diff.get("ambiente") or "")
        if ambiente == "prod" and not self._drifts_pendentes(os_, "prod"):
            self._resolver_pendencia_automatica(tenant_id, os_, actor)
        return check

    # ------------------------------------------------------------------- privados
    async def _verificar_snapshot(
        self,
        os_: OS,
        snapshot: Snapshot,
        ambiente: str,
        registros: list[ResourceRegistry],
        actor: str,
    ) -> list[DriftCheck]:
        esperados = self._recursos_esperados(snapshot, os_)
        agora = self._relogio.agora()
        checks: list[DriftCheck] = []
        for registro in sorted(registros, key=lambda r: r.external_key):
            esperado = esperados.get(registro.external_key)
            if esperado is None:
                continue  # registro sem recurso no grafo do snapshot: fora da régua
            nome_obter, _, _ = _OPERACOES[registro.tipo_sfmc]
            estado_real = await getattr(self._sfmc, nome_obter)(registro.external_key)
            check = regras_drift.avaliar_recurso(
                snapshot_id=snapshot.id,
                ambiente=ambiente,
                tipo_sfmc=registro.tipo_sfmc,
                external_key=registro.external_key,
                payload_esperado=esperado["payload"],
                estado_real=estado_real,
                agora=agora,
            )
            self._repo.adicionar_drift_check(check)
            checks.append(check)
        com_drift = [c for c in checks if c.estado != "em_sincronia"]
        if com_drift:
            self._evento(
                os_,
                "drift.detected",  # §2.3
                {
                    "snapshot_id": str(snapshot.id),
                    "ambiente": ambiente,
                    "recursos": [c.recurso for c in com_drift],
                    "estados": sorted({c.estado for c in com_drift}),
                },
                actor,
            )
            if ambiente == "prod":  # A4: drift em prod → pendência automática bloqueante
                self._abrir_pendencia_automatica(os_, com_drift, actor)
        return checks

    def _recursos_esperados(self, snapshot: Snapshot, os_: OS) -> dict[str, dict[str, Any]]:
        """Recursos que o twin espera (compilador §5.4.1 — puro) por externalKey."""
        jgc = snapshot.conteudo["componentes"]["jgc"]
        jornada = next(
            (
                j
                for j in self._repo.listar_jornadas(os_.id)
                if j.id == uuid.UUID(str(jgc["jornada_id"]))
            ),
            None,
        )
        if jornada is None:
            return {}
        recursos = compilar_recursos(jornada.grafo, str(jgc["hash"]))
        return {item["recurso"]: item for item in recursos}

    def _abrir_pendencia_automatica(self, os_: OS, com_drift: list[DriftCheck], actor: str) -> None:
        abertas = [
            p
            for p in self._repo.listar_pendencias(os_.id)
            if p.origem == ORIGEM_PENDENCIA_DRIFT and p.status == "aberta"
        ]
        if abertas:
            return  # dedupe: uma pendência automática aberta por vez (A4)
        recursos = ", ".join(c.recurso for c in com_drift)
        self._servico_os.abrir_pendencia(
            os_.tenant_id,
            os_.id,
            titulo="Drift detectado em PROD — jornada editada fora do twin (§5.4.5)",
            tipo="issue",
            descricao=(
                "O monitor de drift encontrou divergência twin ↔ SFMC em prod: "
                f"{recursos}. Resolva via POST /drift/{{id}}/resolver "
                "(adopt/enforce/excecao) — §8-M9-A4."
            ),
            severidade="alta",
            bloqueante=True,
            bloqueia_etapa=None,  # bloqueia qualquer avanço de fase
            accountable=None,
            origem=ORIGEM_PENDENCIA_DRIFT,
            via_ai=False,  # monitor determinístico (§5.4)
            actor=actor,
        )

    def _drifts_pendentes(self, os_: OS, ambiente: str) -> list[DriftCheck]:
        """Último check por recurso no ambiente: drift sem resolução ⇒ pendente."""
        ultimos: dict[str, DriftCheck] = {}
        for snapshot in self._repo.listar_snapshots(os_.id):
            for check in self._repo.listar_drift_checks(snapshot.id):
                if str(check.diff.get("ambiente")) == ambiente:
                    ultimos[check.recurso] = check  # listagem em ordem: o último vence
        return [c for c in ultimos.values() if c.estado != "em_sincronia" and c.resolucao is None]

    def _resolver_pendencia_automatica(self, tenant_id: str, os_: OS, actor: str) -> None:
        for pendencia in self._repo.listar_pendencias(os_.id):
            if pendencia.origem == ORIGEM_PENDENCIA_DRIFT and pendencia.status == "aberta":
                self._servico_os.resolver_pendencia(tenant_id, pendencia.id, actor)

    def _drift_da_os(self, tenant_id: str, drift_id: uuid.UUID) -> tuple[DriftCheck, OS]:
        check = self._repo.obter_drift_check(drift_id)
        if check is not None:
            snapshot = self._repo.obter_snapshot(check.snapshot_id)
            if snapshot is not None:
                os_ = self._repo.obter_os(tenant_id, snapshot.os_id)
                if os_ is not None:
                    return check, os_
        raise NaoEncontrado(f"Drift check {drift_id} não encontrado no tenant {tenant_id!r}.")

    def _evento(self, os_: OS, tipo: str, payload: dict[str, Any], actor: str) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=False,  # §5.4: caminho 100% determinístico
                created_at=self._relogio.agora(),
            )
        )
