"""Casos de uso do M2 · Esteira de Produção ex-Hike (§8-M2) — orquestram o domínio via ports.

- `obter_workflow`: materializa lazy as 7 etapas padrão na primeira consulta da OS
  (Criativos nasce com as 4 subtarefas — A1).
- `atualizar_etapa` (PATCH /os/{id}/workflow): estado (dependência insatisfeita →
  DependenciaInsatisfeita/409 — A2), responsável, SLA e marcações de checklist.
- `importar_hike` (POST /admin/hike/import): export JSON do Hike → OS + 7 etapas com
  `hike_ref`; histórico preservado no outbox (`hike.card_imported`) e log em
  `hike_import_log` (A3). Import é histórico: estados/checklist entram como vieram
  do Hike, sem validação de transição.
"""

import uuid
from typing import Any

from application.ports.clock import ClockPort
from application.ports.repositorio_workflow import RepositorioWorkflow
from application.services.os_service import ServicoOs
from domain.campanha.modelos import EventoDominio
from domain.esteira import workflow as regras
from domain.esteira.modelos import ETAPAS, EtapaWorkflow, HikeImportLog


class ServicoWorkflow:
    def __init__(
        self, repositorio: RepositorioWorkflow, relogio: ClockPort, servico_os: ServicoOs
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._servico_os = servico_os

    # ------------------------------------------------------------- Workflow
    def obter_workflow(self, tenant_id: str, os_id: uuid.UUID) -> list[EtapaWorkflow]:
        """GET /os/{id}/workflow — cria as 7 etapas padrão na primeira consulta (lazy)."""
        os_ = self._servico_os.obter_os(tenant_id, os_id)  # NaoEncontrado → 404
        etapas = self._repo.listar_etapas(os_.id)
        if not etapas:
            etapas = regras.etapas_padrao(os_.id)
            for etapa in etapas:
                self._repo.adicionar_etapa(etapa)
        return etapas

    def atualizar_etapa(
        self,
        tenant_id: str,
        os_id: uuid.UUID,
        nome_etapa: str,
        *,
        estado: str | None = None,
        responsavel: uuid.UUID | None = None,
        sla_dias: int | None = None,
        checklist: list[dict[str, Any]] | None = None,
        actor: str,
    ) -> list[EtapaWorkflow]:
        """PATCH /os/{id}/workflow — devolve o workflow completo atualizado."""
        etapas = self.obter_workflow(tenant_id, os_id)
        etapa = next(e for e in etapas if e.nome == nome_etapa)  # nome é Literal na API
        agora = self._relogio.agora()

        if responsavel is not None:
            etapa.responsavel = responsavel
        if sla_dias is not None:
            etapa.sla_dias = sla_dias
        for marcacao in checklist or []:
            regras.marcar_item(
                etapa, marcacao["item"], bool(marcacao.get("feito", True)), actor, agora
            )
        if estado is not None and estado != etapa.estado:
            regras.validar_mudanca_estado(etapa, estado, etapas)  # A2: 409
            anterior = etapa.estado
            etapa.estado = estado
            self._evento(
                tenant_id,
                os_id,
                "workflow.etapa_estado_alterado",
                {"etapa": etapa.nome, "de": anterior, "para": estado},
                actor,
            )
        self._repo.salvar_etapa(etapa)
        return etapas

    # ----------------------------------------------------------- Hike import
    def importar_hike(
        self,
        tenant_id: str,
        cards: list[dict[str, Any]],
        *,
        created_by: uuid.UUID,
        actor: str,
    ) -> list[dict[str, Any]]:
        """POST /admin/hike/import — um resultado {card_id, status, os_id?, codigo?} por card."""
        agora = self._relogio.agora()
        ja_importados = {
            log.hike_card_id for log in self._repo.listar_hike_logs(tenant_id) if log.status == "ok"
        }
        resultados: list[dict[str, Any]] = []
        for card in cards:
            card_id = card["card_id"]
            if card_id in ja_importados:
                self._log_hike(tenant_id, None, card_id, "duplicado", {"motivo": "já importado"})
                resultados.append({"card_id": card_id, "status": "duplicado"})
                continue
            os_ = self._servico_os.criar_os(
                tenant_id,
                nome=card["titulo"],
                tshirt=card.get("tshirt", "M"),
                briefing=card.get("briefing", {}),
                created_by=created_by,
            )
            self._criar_etapas_do_card(os_.id, card, agora)
            self._evento(
                tenant_id,
                os_.id,
                "hike.card_imported",
                {
                    "card_id": card_id,
                    "codigo": os_.codigo,
                    "historico": card.get("historico", []),  # A3: histórico preservado
                },
                actor,
            )
            self._log_hike(
                tenant_id, os_.id, card_id, "ok", {"codigo": os_.codigo, "titulo": card["titulo"]}
            )
            ja_importados.add(card_id)
            resultados.append(
                {"card_id": card_id, "status": "ok", "os_id": os_.id, "codigo": os_.codigo}
            )
        return resultados

    def _criar_etapas_do_card(self, os_id: uuid.UUID, card: dict[str, Any], agora: Any) -> None:
        """7 etapas canônicas; dados do card (estado/checklist/sla) prevalecem sobre o padrão."""
        do_card: dict[str, dict[str, Any]] = {e["nome"]: e for e in card.get("etapas", [])}
        hike_ref = {
            "card_id": card["card_id"],
            "importado_em": agora.isoformat(),
            "url_arquivada": card.get("url"),
        }
        for ordem, nome in enumerate(ETAPAS, start=1):
            dados = do_card.get(nome, {})
            checklist = dados.get("checklist") or regras.checklist_padrao(nome)
            self._repo.adicionar_etapa(
                EtapaWorkflow(
                    id=uuid.uuid4(),
                    os_id=os_id,
                    ordem=ordem,
                    nome=nome,
                    responsavel=None,
                    sla_dias=dados.get("sla_dias"),
                    estado=dados.get("estado", "pendente"),
                    checklist=[dict(item) for item in checklist],
                    dependencias=regras.dependencias_padrao(nome),
                    hike_ref=dict(hike_ref),
                )
            )

    # -------------------------------------------------------------- Interno
    def _log_hike(
        self,
        tenant_id: str,
        os_id: uuid.UUID | None,
        card_id: str,
        status: str,
        detalhe: dict[str, Any],
    ) -> None:
        self._repo.adicionar_hike_log(
            HikeImportLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                os_id=os_id,
                hike_card_id=card_id,
                status=status,
                detalhe=detalhe,
                created_at=self._relogio.agora(),
            )
        )

    def _evento(
        self,
        tenant_id: str,
        os_id: uuid.UUID,
        tipo: str,
        payload: dict[str, Any],
        actor: str,
    ) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=tenant_id,
                os_id=os_id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=False,
                created_at=self._relogio.agora(),
            )
        )
