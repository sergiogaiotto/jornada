"""Casos de uso do M1 · Núcleo OS/governança (§8-M1) — orquestram o domínio via ports.

Toda mutação relevante grava o outbox `domain_event` (§2.3):
os.phase_changed · pendencia.opened|resolved|accepted · gate.passed|blocked.
Relógio via ClockPort; persistência via RepositorioOs. Nenhuma escrita de saúde:
`saude()` apenas deriva (espelho da view os_saude §4.1).
"""

import uuid
from typing import Any

from application.ports.clock import ClockPort
from application.ports.repositorio_os import RepositorioOs
from domain.campanha import fases, saude
from domain.campanha import pendencias as regras_pendencia
from domain.campanha import sla as regras_sla
from domain.campanha.erros import (
    AvancoBloqueadoPorPendencia,
    CodigoDuplicado,
    NaoEncontrado,
)
from domain.campanha.modelos import OS, EventoDominio, Pendencia


class ServicoOs:
    def __init__(self, repositorio: RepositorioOs, relogio: ClockPort) -> None:
        self._repo = repositorio
        self._relogio = relogio

    # ------------------------------------------------------------------ OS
    def criar_os(
        self,
        tenant_id: str,
        *,
        nome: str,
        tshirt: str,
        briefing: dict[str, Any],
        created_by: uuid.UUID,
        codigo: str | None = None,
    ) -> OS:
        agora = self._relogio.agora()
        # Achado 22/UAT5: sequência e duplicidade são DENTRO do tenant. Globais, o
        # número da OS contava o volume de todos os clientes e o 409 virava oráculo de
        # existência (código alheio → "Já existe OS com código ...", enumerável).
        if codigo is None:
            sequencial = self._repo.proximo_sequencial_os(agora.year, tenant_id)
            codigo = f"OS-{agora.year}-{sequencial:04d}"
        if self._repo.obter_os_por_codigo(codigo, tenant_id) is not None:
            raise CodigoDuplicado(f"Já existe OS com código {codigo!r} (unique §4.1).")
        os_ = OS(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            codigo=codigo,
            nome=nome,
            tshirt=tshirt,
            fase="pensada",
            briefing=briefing,
            frozen=None,
            created_by=created_by,
            created_at=agora,
            updated_at=agora,
        )
        self._repo.adicionar_os(os_)
        return os_

    def listar_os(self, tenant_id: str, *, limit: int, offset: int) -> list[OS]:
        return self._repo.listar_os(tenant_id, limit, offset)

    def obter_os(self, tenant_id: str, os_id: uuid.UUID) -> OS:
        os_ = self._repo.obter_os(tenant_id, os_id)
        if os_ is None:
            raise NaoEncontrado(f"OS {os_id} não encontrada no tenant {tenant_id!r}.")
        return os_

    def mudar_fase(self, tenant_id: str, os_id: uuid.UUID, fase_destino: str, actor: str) -> OS:
        """POST /os/{id}/fase — só transições legais; portões checados (§8-M1)."""
        os_ = self.obter_os(tenant_id, os_id)
        agora = self._relogio.agora()
        fases.validar_transicao(os_.fase, fase_destino)
        try:
            fases.validar_portao_pendencias(self._repo.listar_pendencias(os_.id), fase_destino)
        except AvancoBloqueadoPorPendencia as exc:
            self._evento(
                os_,
                "gate.blocked",
                {
                    "portao": "pendencias",
                    "fase_destino": fase_destino,
                    "pendencias": [p.numero for p in exc.pendencias],
                },
                actor,
            )
            raise
        self._evento(
            os_, "gate.passed", {"portao": "pendencias", "fase_destino": fase_destino}, actor
        )
        fase_anterior = os_.fase
        os_.fase = fase_destino
        os_.updated_at = agora
        self._repo.salvar_os(os_)
        self._evento(os_, "os.phase_changed", {"de": fase_anterior, "para": fase_destino}, actor)
        return os_

    # ----------------------------------------------------------- Pendências
    def abrir_pendencia(
        self,
        tenant_id: str,
        os_id: uuid.UUID,
        *,
        titulo: str,
        tipo: str | None,
        descricao: str | None,
        severidade: str | None,
        bloqueante: bool,
        bloqueia_etapa: str | None,
        accountable: uuid.UUID | None,
        origem: str | None,
        via_ai: bool,
        actor: str,
    ) -> Pendencia:
        os_ = self.obter_os(tenant_id, os_id)
        agora = self._relogio.agora()
        pendencia = Pendencia(
            id=uuid.uuid4(),
            os_id=os_.id,
            numero=self._repo.proximo_numero_pendencia(os_.id),
            tipo=tipo,
            titulo=titulo,
            descricao=descricao,
            severidade=severidade,
            bloqueante=bloqueante,
            bloqueia_etapa=bloqueia_etapa,
            status="aberta",
            accountable=accountable,
            aceite=None,
            origem=origem,
            via_ai=via_ai,
            created_at=agora,
        )
        self._repo.adicionar_pendencia(pendencia)
        if bloqueante:  # SLA para de correr: estado bloqueado_pendencia (§4.1/§8-M1)
            for clock in self._repo.listar_sla_clocks(os_.id):
                if clock.estado == "correndo":
                    regras_sla.bloquear_por_pendencia(
                        clock, agora, motivo=f"pendencia #{pendencia.numero}"
                    )
                    self._repo.salvar_sla_clock(clock)
        self._evento(
            os_,
            "pendencia.opened",
            {
                "pendencia_id": str(pendencia.id),
                "numero": pendencia.numero,
                "titulo": titulo,
                "bloqueante": bloqueante,
                "severidade": severidade,
            },
            actor,
            via_ai=via_ai,
        )
        return pendencia

    def listar_pendencias(self, tenant_id: str, os_id: uuid.UUID) -> list[Pendencia]:
        """GET /os/{id}/pendencias (emenda B01) — pendências da OS em ordem de `numero`.

        Leitura pura, sem efeito: a tela T3 e o War Room precisam saber o que já foi
        aberto (e o que ainda bloqueia o GO) depois de um reload/restart — antes disso
        só existia o POST, e o estado vivia na sessão do navegador."""
        os_ = self.obter_os(tenant_id, os_id)  # tenant errado/inexistente → 404
        return self._repo.listar_pendencias(os_.id)

    def resolver_pendencia(self, tenant_id: str, pendencia_id: uuid.UUID, actor: str) -> Pendencia:
        pendencia, os_ = self._exigir_pendencia(tenant_id, pendencia_id)
        regras_pendencia.resolver(pendencia)
        self._repo.salvar_pendencia(pendencia)
        self._retomar_clocks_se_desbloqueada(os_)
        self._evento(
            os_,
            "pendencia.resolved",
            {"pendencia_id": str(pendencia.id), "numero": pendencia.numero},
            actor,
        )
        return pendencia

    def aceitar_pendencia(
        self,
        tenant_id: str,
        pendencia_id: uuid.UUID,
        *,
        por: uuid.UUID,
        justificativa: str,
        actor: str,
    ) -> Pendencia:
        pendencia, os_ = self._exigir_pendencia(tenant_id, pendencia_id)
        agora = self._relogio.agora()
        regras_pendencia.aceitar(pendencia, por=por, justificativa=justificativa, em=agora)
        self._repo.salvar_pendencia(pendencia)
        self._retomar_clocks_se_desbloqueada(os_)
        self._evento(
            os_,
            "pendencia.accepted",
            {
                "pendencia_id": str(pendencia.id),
                "numero": pendencia.numero,
                "por": str(por),
                "justificativa": pendencia.aceite["justificativa"] if pendencia.aceite else None,
            },
            actor,
        )
        return pendencia

    # ---------------------------------------------------------------- Saúde
    def saude_da_os(self, tenant_id: str, os_id: uuid.UUID) -> str:
        """DERIVADA — nenhuma escrita (A3); espelho da view os_saude (§4.1)."""
        os_ = self.obter_os(tenant_id, os_id)
        return saude.derivar_saude(
            self._repo.listar_pendencias(os_.id),
            self._repo.listar_sla_clocks(os_.id),
            self._relogio.agora(),
        )

    # -------------------------------------------------------------- Interno
    def _exigir_pendencia(self, tenant_id: str, pendencia_id: uuid.UUID) -> tuple[Pendencia, OS]:
        pendencia = self._repo.obter_pendencia(pendencia_id)
        if pendencia is not None:
            os_ = self._repo.obter_os(tenant_id, pendencia.os_id)
            if os_ is not None:
                return pendencia, os_
        raise NaoEncontrado(f"Pendência {pendencia_id} não encontrada no tenant {tenant_id!r}.")

    def _retomar_clocks_se_desbloqueada(self, os_: OS) -> None:
        """Sem pendência aberta+bloqueante restante → clocks bloqueados voltam a correr."""
        abertas_bloqueantes = [
            p for p in self._repo.listar_pendencias(os_.id) if p.status == "aberta" and p.bloqueante
        ]
        if abertas_bloqueantes:
            return
        agora = self._relogio.agora()
        for clock in self._repo.listar_sla_clocks(os_.id):
            if clock.estado == "bloqueado_pendencia":
                regras_sla.retomar(clock, agora)
                self._repo.salvar_sla_clock(clock)

    def _evento(
        self,
        os_: OS,
        tipo: str,
        payload: dict[str, Any],
        actor: str,
        via_ai: bool = False,
    ) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=via_ai,
                created_at=self._relogio.agora(),
            )
        )
